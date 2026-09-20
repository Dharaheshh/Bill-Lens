"""
Main orchestrator runner: policy_ingest and bill_audit phases.
SPEC §10.2 — all stages wrapped with fallback, watchdog timeout 120s.
"""
import asyncio
import hashlib
import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.action import run_action_agent
from app.agents.audit import run_audit_agent
from app.agents.policy import run_policy_agent
from app.db import AsyncSessionLocal
from app.engine.normalizer import normalize_lines
from app.engine.rules import apply_rules
from app.engine.simulator import simulate_claim
from app.engine.totals import calculate_summary
from app.models import Bill, Policy, Run
from app.orchestrator.events import RunContext, drop_queue
from app.rag.ingest import ingest_pdf
from app.schemas import (
    ActionPack,
    ExtractedBill,
    Finding,
    MatchedLine,
    ResolvedPolicy,
    RunResult,
    Summary,
)

logger = logging.getLogger(__name__)

WATCHDOG_TIMEOUT = 120


def _build_resolved_policy(terms: dict, is_insured: bool) -> ResolvedPolicy:
    """Build ResolvedPolicy from confirmed PolicyTerms."""
    if not is_insured:
        return ResolvedPolicy(is_insured=False)

    sum_insured = None
    room_cap = None
    copay_pct = 0.0
    proportionate = False
    term_evidence: dict[str, str] = {}

    si_term = terms.get("sum_insured")
    if si_term and si_term.get("status") == "extracted":
        sum_insured = si_term.get("value")

    rr_term = terms.get("room_rent_cap")
    if rr_term and rr_term.get("status") == "extracted":
        val = rr_term.get("value")
        kind = rr_term.get("room_cap_kind", "absolute")
        if kind == "pct_si" and sum_insured:
            room_cap = round(sum_insured * val / 100, 2)
        else:
            room_cap = val

    cp_term = terms.get("copay_pct")
    if cp_term and cp_term.get("status") == "extracted":
        copay_pct = float(cp_term.get("value") or 0)

    pd_term = terms.get("proportionate_deduction")
    if pd_term and pd_term.get("status") == "extracted":
        proportionate = bool(pd_term.get("value", False))

    return ResolvedPolicy(
        is_insured=True,
        sum_insured=sum_insured,
        room_rent_cap_per_day=room_cap,
        copay_pct=copay_pct,
        proportionate_deduction=proportionate,
        term_evidence=term_evidence,
    )


async def _update_run(session: AsyncSession, run_id: str, **kwargs) -> None:
    await session.execute(update(Run).where(Run.id == run_id).values(**kwargs))
    await session.commit()


async def run_policy_ingest(
    run_id: str,
    pdf_path: str,
    policy_id: str,
    document_id: str | None,
    session_id: str,
) -> None:
    """Background task: ingest policy PDF and extract terms."""
    async with AsyncSessionLocal() as session:
        ctx = RunContext(run_id=run_id, session=session)
        await _update_run(session, run_id, status="ingesting")
        try:
            async with asyncio.timeout(WATCHDOG_TIMEOUT):
                ctx.emit("policy", "stage_start", "Ingesting policy PDF")

                # Ingest PDF if not already done
                if not document_id:
                    doc_id = await ingest_pdf(session, pdf_path, kind="policy", name=Path(pdf_path).name, session_id=session_id)
                else:
                    doc_id = document_id

                ctx.emit("policy", "stage_end", f"PDF ingested: doc_id={doc_id}")

                # Run policy agent
                terms = await run_policy_agent(session, str(doc_id), ctx)

                # Save terms to policy
                terms_dict = {k: v.model_dump() for k, v in terms.items()}
                await session.execute(
                    update(Policy).where(Policy.id == policy_id).values(terms=terms_dict)
                )
                await session.commit()
                await _update_run(session, run_id, status="done")
                ctx.emit("orchestrator", "done", f"Policy ingested: {sum(1 for t in terms.values() if t.status == 'extracted')} terms extracted")
        except Exception as e:
            logger.error("Policy ingest failed: %s", e)
            ctx.emit("orchestrator", "error", f"Policy ingest failed: {e}")
            await _update_run(session, run_id, status="failed", error=str(e))
        finally:
            drop_queue(run_id)


async def run_bill_audit_phase1(run_id: str, bill_id: str, auto_confirm: bool = False) -> None:
    """Phase 1: extract bill from sample/uploaded file → normalise → await_verification."""
    async with AsyncSessionLocal() as session:
        ctx = RunContext(run_id=run_id, session=session)
        await _update_run(session, run_id, status="extracting", phase="phase1")
        try:
            async with asyncio.timeout(WATCHDOG_TIMEOUT):
                # Fetch bill
                bill_res = await session.execute(select(Bill).where(Bill.id == bill_id))
                bill_row = bill_res.scalar()
                if not bill_row:
                    raise ValueError(f"Bill {bill_id} not found")

                ctx.emit("extraction", "stage_start", f"Loading bill: {bill_row.filename}")

                # Use stored extracted JSON if available, else make a simple extraction from sample
                if bill_row.extracted:
                    extracted = ExtractedBill.model_validate(bill_row.extracted)
                else:
                    # Minimal stub for sample bills: load from golden fixture
                    extracted = _load_sample_extraction(bill_row.filename or "sample-a")
                    # Save it
                    await session.execute(
                        update(Bill).where(Bill.id == bill_id).values(extracted=extracted.model_dump())
                    )
                    await session.commit()

                ctx.emit("extraction", "stage_end", f"Extracted {len(extracted.lines)} lines")

                # Normalize
                ctx.emit("normalizer", "stage_start", f"Normalizing {len(extracted.lines)} lines")
                lines = await normalize_lines(session, extracted.lines)
                ctx.emit("normalizer", "stage_end", f"Normalized: {sum(1 for l in lines if l.match_method != 'unmatched')} matched")

                # Save verified lines
                verified_dict = [l.model_dump() for l in lines]
                await session.execute(
                    update(Bill).where(Bill.id == bill_id).values(verified=verified_dict)
                )
                await session.commit()

                if auto_confirm:
                    await _run_phase2_internal(run_id, bill_id, extracted, lines, bill_row, session, ctx)
                else:
                    await _update_run(session, run_id, status="awaiting_verification", phase="phase1")
                    ctx.emit("orchestrator", "stage_end", "Bill extracted — awaiting user verification")
        except Exception as e:
            logger.error("Phase 1 failed: %s", e)
            ctx.emit("orchestrator", "error", f"Phase 1 failed: {e}")
            await _update_run(session, run_id, status="failed", error=str(e))
        finally:
            if auto_confirm:
                drop_queue(run_id)


async def run_bill_audit_phase2(
    run_id: str,
    bill_id: str,
    lines: list[MatchedLine],
    is_insured: bool,
    policy_id: str | None,
) -> None:
    """Phase 2: rules → audit agent → simulator → action agent → RunResult."""
    async with AsyncSessionLocal() as session:
        ctx = RunContext(run_id=run_id, session=session)
        await _update_run(session, run_id, status="auditing", phase="phase2")

        # Fetch bill and policy
        bill_res = await session.execute(select(Bill).where(Bill.id == bill_id))
        bill_row = bill_res.scalar()
        extracted = ExtractedBill.model_validate(bill_row.extracted) if bill_row and bill_row.extracted else ExtractedBill(lines=[l.model_dump() for l in lines])

        policy_terms: dict = {}
        if policy_id:
            pol_res = await session.execute(select(Policy).where(Policy.id == policy_id))
            pol_row = pol_res.scalar()
            if pol_row and pol_row.terms:
                policy_terms = pol_row.terms

        policy = _build_resolved_policy(policy_terms, is_insured)

        try:
            async with asyncio.timeout(WATCHDOG_TIMEOUT):
                await _run_phase2_internal(run_id, bill_id, extracted, lines, bill_row, session, ctx, policy, policy_terms)
        except Exception as e:
            logger.error("Phase 2 failed: %s", e)
            ctx.emit("orchestrator", "error", f"Phase 2 failed: {e}")
            await _update_run(session, run_id, status="failed", error=str(e))
        finally:
            drop_queue(run_id)


async def _run_phase2_internal(
    run_id: str,
    bill_id: str,
    extracted: ExtractedBill,
    lines: list[MatchedLine],
    bill_row,
    session: AsyncSession,
    ctx: RunContext,
    policy: ResolvedPolicy | None = None,
    policy_terms: dict | None = None,
) -> None:
    if policy is None:
        policy = ResolvedPolicy(is_insured=bill_row.is_insured if bill_row else False)
    if policy_terms is None:
        policy_terms = {}

    # Rules
    ctx.emit("rules", "stage_start", f"Running R1-R6 on {len(lines)} lines")
    findings, evidence = await apply_rules(session, extracted, lines, policy)
    all_evidence = ctx.evidence.get_all()
    # Add rule-generated evidence
    for ev in evidence:
        ctx.evidence.add([ev])
    ctx.emit("rules", "stage_end", f"Rules: {len(findings)} findings ({sum(1 for f in findings if f.severity=='red')} red)")

    # Audit Agent
    try:
        findings = await run_audit_agent(session, lines, findings, policy_terms, ctx)
    except Exception as e:
        ctx.emit("audit", "warning", f"Audit agent error: {e} — baseline findings stand")

    # Simulator
    ctx.emit("simulator", "stage_start", "Running simulator")
    # collect catalog_non_payable from lines that are matched non-payable
    catalog_non_payable: set[int] = set()
    from sqlalchemy import select as _select
    from app.models import CatalogItem as _CatalogItem
    matched_ids = [l.catalog_id for l in lines if l.catalog_id is not None]
    if matched_ids:
        try:
            _res = await session.execute(_select(_CatalogItem).where(_CatalogItem.id.in_(matched_ids)))
            for _item in _res.scalars():
                if _item.non_payable:
                    catalog_non_payable.add(_item.id)
        except Exception as _e:
            logger.warning("Could not fetch catalog for simulator: %s", _e)

    simulator_result, c1_findings = simulate_claim(extracted, lines, policy, findings, catalog_non_payable)

    # Register C1 findings evidence in EvidenceStore and update evidence_ids
    for c1f in c1_findings:
        c1_ev = getattr(c1f, "_c1_evidence", None)
        if c1_ev is not None:
            [ev_id] = ctx.evidence.add([c1_ev])
            c1f.evidence_ids = [ev_id]
        findings.append(c1f)

    ctx.emit("simulator", "stage_end", f"Simulator: insurer pays ₹{simulator_result.insurer_pays:,.0f}, patient pays ₹{simulator_result.patient_pays:,.0f}")

    # Summary
    summary = calculate_summary(extracted, findings, simulator_result)
    summary.agent_stats = ctx.agent_stats()

    # Action Agent
    action_pack: ActionPack | None = None
    try:
        action_pack = await run_action_agent(
            findings=findings,
            simulator=simulator_result,
            summary=summary,
            hospital_name=extracted.hospital_name or "the hospital",
            bill_date=str(extracted.bill_date or ""),
            ctx=ctx,
        )
    except Exception as e:
        ctx.emit("action", "warning", f"Action agent failed: {e} — no action pack")

    # Build RunResult
    run_result = RunResult(
        run_id=run_id,
        bill=extracted,
        lines=lines,
        policy_terms={k: v if not isinstance(v, dict) else v for k, v in policy_terms.items()},
        policy=policy,
        findings=findings,
        evidence=ctx.evidence.get_all(),
        simulator=simulator_result,
        summary=summary,
        action_pack=action_pack,
        mode="live",
    )

    # Persist
    await session.execute(
        update(Run).where(Run.id == run_id).values(
            status="done",
            result=run_result.model_dump(),
        )
    )
    await session.commit()
    ctx.emit("orchestrator", "done", "Run complete!", data={"agent_stats": summary.agent_stats})


def _load_sample_extraction(filename: str) -> ExtractedBill:
    """Load golden line fixture for sample bills."""
    from app.schemas import BillLine
    import os

    sample_id = "sample-a-ortho-insured"
    if "sample-b" in (filename or ""):
        sample_id = "sample-b-pctsi-insured"
    elif "sample-c" in (filename or ""):
        sample_id = "sample-c-uninsured-photo"

    fixture_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "golden" / f"{sample_id}.lines.json"
    if fixture_path.exists():
        with open(fixture_path) as f:
            raw = json.load(f)
        lines = [BillLine(**l) for l in raw]
        return ExtractedBill(
            hospital_name="Demo General Hospital",
            stated_total=sum(l.amount for l in lines),
            lines=lines,
        )
    return ExtractedBill(lines=[], hospital_name="Demo Hospital")
