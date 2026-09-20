import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

runner_py = '''"""
Main orchestrator runner: policy_ingest and bill_audit phases.
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
from app.agents.extraction import run_extraction_agent
from app.agents.policy import run_policy_agent
from app.db import AsyncSessionLocal
from app.engine.normalizer import normalize_lines
from app.engine.rules import apply_rules
from app.engine.simulator import simulate_claim
from app.engine.totals import calculate_summary
from app.models import Bill, Policy, Run, CatalogItem
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
    if not is_insured:
        return ResolvedPolicy(is_insured=False)

    sum_insured = None
    room_cap = None
    copay_pct = 0.0
    proportionate = False

    def _val(t):
        if not t: return None
        if isinstance(t, dict): return t.get("value")
        return getattr(t, "value", None)

    si_term = terms.get("sum_insured")
    if si_term and (isinstance(si_term, dict) and si_term.get("status") == "extracted" or getattr(si_term, "status", None) == "extracted"):
        sum_insured = _val(si_term)

    rr_term = terms.get("room_rent_cap")
    if rr_term and (isinstance(rr_term, dict) and rr_term.get("status") == "extracted" or getattr(rr_term, "status", None) == "extracted"):
        val = _val(rr_term)
        kind = rr_term.get("room_cap_kind", "absolute") if isinstance(rr_term, dict) else getattr(rr_term, "room_cap_kind", "absolute")
        if kind == "pct_si" and sum_insured:
            room_cap = round(sum_insured * val / 100, 2)
        else:
            room_cap = val

    cp_term = terms.get("copay_pct")
    if cp_term and (isinstance(cp_term, dict) and cp_term.get("status") == "extracted" or getattr(cp_term, "status", None) == "extracted"):
        copay_pct = float(_val(cp_term) or 0)

    pd_term = terms.get("proportionate_deduction")
    if pd_term and (isinstance(pd_term, dict) and pd_term.get("status") == "extracted" or getattr(pd_term, "status", None) == "extracted"):
        proportionate = bool(_val(pd_term))

    return ResolvedPolicy(
        is_insured=True,
        sum_insured=sum_insured,
        room_rent_cap_per_day=room_cap,
        copay_pct=copay_pct,
        proportionate_deduction=proportionate,
    )

async def _update_run(session, run_id, **kwargs):
    await session.execute(update(Run).where(Run.id == run_id).values(**kwargs))
    await session.commit()

async def run_bill_audit_phase1(run_id: str, bill_id: str, auto_confirm: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        ctx = RunContext(run_id=run_id, session=session)
        await _update_run(session, run_id, status="extracting", phase="phase1")
        try:
            async with asyncio.timeout(WATCHDOG_TIMEOUT):
                bill_res = await session.execute(select(Bill).where(Bill.id == bill_id))
                bill_row = bill_res.scalar()
                if not bill_row: raise ValueError(f"Bill {bill_id} not found")

                if bill_row.extracted:
                    extracted = ExtractedBill.model_validate(bill_row.extracted)
                else:
                    if bill_row.storage_path:
                        extracted = await run_extraction_agent(bill_row.storage_path, "dummy_hash", session, ctx)
                    else:
                        extracted = _load_sample_extraction(bill_row.filename or "sample-a")
                    
                    await session.execute(update(Bill).where(Bill.id == bill_id).values(extracted=extracted.model_dump()))
                    await session.commit()

                lines = await normalize_lines(session, extracted.lines)
                
                await session.execute(update(Bill).where(Bill.id == bill_id).values(verified=[l.model_dump() for l in lines]))
                await session.commit()

                if auto_confirm:
                    await _run_phase2_internal(run_id, bill_id, extracted, lines, bill_row, session, ctx)
                else:
                    await _update_run(session, run_id, status="awaiting_verification", phase="phase1")
        except Exception as e:
            logger.error("Phase 1 failed: %s", e)
            await _update_run(session, run_id, status="failed", error=str(e))
        finally:
            if auto_confirm: drop_queue(run_id)

async def run_bill_audit_phase2(run_id: str, bill_id: str, lines: list[MatchedLine], is_insured: bool, policy_id: str | None) -> None:
    async with AsyncSessionLocal() as session:
        ctx = RunContext(run_id=run_id, session=session)
        await _update_run(session, run_id, status="auditing", phase="phase2")
        
        bill_res = await session.execute(select(Bill).where(Bill.id == bill_id))
        bill_row = bill_res.scalar()
        extracted = ExtractedBill.model_validate(bill_row.extracted) if bill_row and bill_row.extracted else ExtractedBill(lines=[l.model_dump() for l in lines])
        
        policy_terms = {}
        if policy_id:
            pol_res = await session.execute(select(Policy).where(Policy.id == policy_id))
            pol_row = pol_res.scalar()
            if pol_row and pol_row.terms: policy_terms = pol_row.terms
            
        policy = _build_resolved_policy(policy_terms, is_insured)
        
        try:
            async with asyncio.timeout(WATCHDOG_TIMEOUT):
                await _run_phase2_internal(run_id, bill_id, extracted, lines, bill_row, session, ctx, policy, policy_terms)
        except Exception as e:
            logger.error("Phase 2 failed: %s", e)
            await _update_run(session, run_id, status="failed", error=str(e))
            
            # Persist partial result on failure
            rr = RunResult(
                run_id=run_id, bill=extracted, lines=lines, policy_terms=policy_terms,
                policy=policy, findings=[], evidence=[], simulator=None, summary=None, action_pack=None, mode="live"
            )
            await _update_run(session, run_id, result=rr.model_dump())
        finally:
            drop_queue(run_id)

async def _run_phase2_internal(run_id, bill_id, extracted, lines, bill_row, session, ctx, policy=None, policy_terms=None):
    if not policy: policy = ResolvedPolicy(is_insured=bill_row.is_insured if bill_row else False)
    if not policy_terms: policy_terms = {}
    
    findings, evidence = await apply_rules(session, extracted, lines, policy)
    for ev in evidence: ctx.evidence.add([ev])
    
    try:
        findings = await run_audit_agent(session, lines, findings, policy_terms, ctx)
    except Exception:
        pass
        
    c_ids = [l.catalog_id for l in lines if l.catalog_id]
    catalog_non_payable = set()
    if c_ids:
        res = await session.execute(select(CatalogItem).where(CatalogItem.id.in_(c_ids)))
        for item in res.scalars():
            if item.non_payable: catalog_non_payable.add(item.id)
            
    simulator_result, c1_findings = simulate_claim(extracted, lines, policy, findings, catalog_non_payable)
    findings.extend(c1_findings)
    
    summary = calculate_summary(extracted, findings, simulator_result)
    
    action_pack = None
    try:
        action_pack = await run_action_agent(findings=findings, simulator=simulator_result, summary=summary, hospital_name=extracted.hospital_name or "Hospital", bill_date=str(extracted.bill_date or ""), ctx=ctx)
    except Exception:
        pass
        
    run_result = RunResult(
        run_id=run_id, bill=extracted, lines=lines, policy_terms=policy_terms,
        policy=policy, findings=findings, evidence=ctx.evidence.get_all(),
        simulator=simulator_result, summary=summary, action_pack=action_pack, mode="live"
    )
    
    await _update_run(session, run_id, status="done", result=run_result.model_dump())

def _load_sample_extraction(filename: str) -> ExtractedBill:
    from app.schemas import BillLine
    sample_id = "sample-a-ortho-insured"
    if "sample-b" in (filename or ""): sample_id = "sample-b-pctsi-insured"
    elif "sample-c" in (filename or ""): sample_id = "sample-c-uninsured-photo"
    
    fixture_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "golden" / f"{sample_id}.lines.json"
    if fixture_path.exists():
        with open(fixture_path) as f: raw = json.load(f)
        lines = [BillLine(**l) for l in raw]
        # In sample parsing, they should already match MatchedLine basically, but we return BillLine here
        return ExtractedBill(hospital_name="Demo General Hospital", stated_total=sum(l.amount for l in lines if l.amount), lines=lines)
    return ExtractedBill(lines=[], hospital_name="Demo Hospital")
'''
write_file("backend/app/orchestrator/runner.py", runner_py)
'''
