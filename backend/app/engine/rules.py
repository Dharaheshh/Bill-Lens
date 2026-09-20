"""
Deterministic rules R1-R6 per SPEC §5.
Pure Python — no LLM, no DB. DB queries are pre-done in runner.py.
Signature: apply_rules(session, bill, lines, policy) -> (findings, evidence)
"""
import logging
import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import CatalogItem
from app.schemas import Evidence, ExtractedBill, Finding, MatchedLine, ResolvedPolicy

logger = logging.getLogger(__name__)

_ABBR = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _ABBR.sub(" ", text.upper().strip())


async def apply_rules(
    session: AsyncSession,
    bill: ExtractedBill,
    lines: list[MatchedLine],
    policy: ResolvedPolicy,
) -> tuple[list[Finding], list[Evidence]]:
    """Run R1-R6 and return (findings, evidence). Evidence IDs are placeholders; caller reassigns via EvidenceStore."""
    findings: list[Finding] = []
    evidence: list[Evidence] = []

    # Pre-fetch catalog info for all matched lines
    catalog_ids = [line.catalog_id for line in lines if line.catalog_id is not None]
    catalog_map: dict[int, CatalogItem] = {}
    if catalog_ids:
        stmt = select(CatalogItem).where(CatalogItem.id.in_(catalog_ids))
        res = await session.execute(stmt)
        for item in res.scalars():
            catalog_map[item.id] = item

    has_room_line = any(line.category == "room" for line in lines)

    # ── R1 ARITHMETIC ──────────────────────────────────────────────────────
    for line in lines:
        if line.qty is not None and line.unit_price is not None:
            expected = round(line.qty * line.unit_price, 2)
            diff = abs(expected - line.amount)
            if diff > 1.0:
                eid = f"ev-r1-{uuid.uuid4().hex[:8]}"
                ev = Evidence(
                    id=eid,
                    type="calc",
                    text=f"Line {line.line_no}: {line.qty} × ₹{line.unit_price} = ₹{expected}, but printed ₹{line.amount} (diff ₹{round(line.amount - expected, 2)})",
                    meta={"line_no": line.line_no},
                )
                evidence.append(ev)
                findings.append(Finding(
                    id=f"F-R1-{uuid.uuid4().hex[:8]}",
                    rule_code="R1",
                    kind="billing",
                    severity="red",
                    origin="rule",
                    line_ids=[line.line_no],
                    title=f"Arithmetic Mismatch — {line.canonical_name or line.raw_text[:30]}",
                    explanation=f"Qty ({line.qty}) × Unit price (₹{line.unit_price}) = ₹{expected}, but amount printed is ₹{line.amount}. Worth asking about.",
                    amount_at_stake=round(diff, 2),
                    confidence="high",
                    evidence_ids=[eid],
                    uncertain=False,
                ))

    # Bill-level R1: sum of lines vs stated_total
    if bill.stated_total is not None:
        line_sum = round(sum(line.amount for line in lines), 2)
        bill_diff = abs(line_sum - bill.stated_total)
        if bill_diff > 1.0:
            eid = f"ev-r1-bill-{uuid.uuid4().hex[:8]}"
            ev = Evidence(
                id=eid,
                type="calc",
                text=f"Lines sum ₹{line_sum:,.0f}, stated total ₹{bill.stated_total:,.0f} (diff ₹{round(bill.stated_total - line_sum, 2):,.0f})",
                meta={},
            )
            evidence.append(ev)
            findings.append(Finding(
                id=f"F-R1-BILL-{uuid.uuid4().hex[:8]}",
                rule_code="R1",
                kind="billing",
                severity="red",
                origin="rule",
                line_ids=[],
                title="Bill Total Mismatch",
                explanation=f"The individual line items sum to ₹{line_sum:,.0f} but the stated total on the bill is ₹{bill.stated_total:,.0f}. Worth asking about.",
                amount_at_stake=round(bill_diff, 2),
                confidence="high",
                evidence_ids=[eid],
                uncertain=False,
            ))

    # ── R2 DUPLICATE ──────────────────────────────────────────────────────
    # Group by (catalog_id or cleaned raw_text, service_date)
    groups: dict[tuple, list[MatchedLine]] = defaultdict(list)
    for line in lines:
        key = (
            line.catalog_id if line.catalog_id is not None else _clean(line.raw_text),
            str(line.service_date) if line.service_date else "unknown",
        )
        groups[key].append(line)

    NON_DAILY_CATS = {"investigation", "procedure", "professional_fee", "nursing", "room"}
    PHARMA_CATS = {"pharmacy", "consumable"}

    for key, group in groups.items():
        if len(group) < 2:
            continue
        # Determine category and catalog
        cat_id = group[0].catalog_id
        cat_obj = catalog_map.get(cat_id) if cat_id else None
        category = group[0].category or (cat_obj.category if cat_obj else None)
        max_per = (cat_obj.max_per_day or 1) if cat_obj else 1

        if category in NON_DAILY_CATS:
            # Count > max_per_day → RED
            if len(group) > max_per:
                extras = group[max_per:]
                extra_ids = [l.line_no for l in extras]
                all_ids = [l.line_no for l in group]
                stake = round(sum(l.amount for l in extras), 2)
                eid = f"ev-r2-{uuid.uuid4().hex[:8]}"
                name = group[0].canonical_name or _clean(group[0].raw_text)
                ev = Evidence(
                    id=eid,
                    type="line",
                    text=f"'{name}' appears {len(group)} times on {key[1]}; max allowed per day is {max_per}",
                    meta={"line_nos": all_ids},
                )
                evidence.append(ev)
                findings.append(Finding(
                    id=f"F-R2-{uuid.uuid4().hex[:8]}",
                    rule_code="R2",
                    kind="billing",
                    severity="red",
                    origin="rule",
                    line_ids=all_ids,
                    title=f"Duplicate Charge — {name}",
                    explanation=f"'{name}' is charged {len(group)} times on {key[1]}, which exceeds the usual maximum of {max_per} per day. Worth asking about.",
                    amount_at_stake=stake,
                    confidence="high",
                    evidence_ids=[eid],
                    uncertain=False,
                ))

        elif category in PHARMA_CATS:
            # ≥2 with IDENTICAL qty AND identical amount → amber uncertain
            seen_combos: dict[tuple, list[MatchedLine]] = defaultdict(list)
            for line in group:
                combo = (line.qty, line.amount)
                seen_combos[combo].append(line)
            for combo, dup_lines in seen_combos.items():
                if len(dup_lines) >= 2:
                    all_ids = [l.line_no for l in dup_lines]
                    extras = dup_lines[1:]
                    stake = round(sum(l.amount for l in extras), 2)
                    eid = f"ev-r2p-{uuid.uuid4().hex[:8]}"
                    name = group[0].canonical_name or _clean(group[0].raw_text)
                    ev = Evidence(
                        id=eid,
                        type="line",
                        text=f"'{name}' appears {len(dup_lines)} times on {key[1]} with same qty {combo[0]} and amount ₹{combo[1]}",
                        meta={"line_nos": all_ids},
                    )
                    evidence.append(ev)
                    findings.append(Finding(
                        id=f"F-R2-{uuid.uuid4().hex[:8]}",
                        rule_code="R2",
                        kind="billing",
                        severity="amber",
                        origin="rule",
                        line_ids=all_ids,
                        title=f"Possible Duplicate — {name}",
                        explanation=f"'{name}' appears {len(dup_lines)} times on {key[1]} with identical qty and amount. May be legitimate re-dosing — worth asking about.",
                        amount_at_stake=stake,
                        confidence="medium",
                        evidence_ids=[eid],
                        uncertain=True,
                    ))

    # ── R3 NON-PAYABLE ────────────────────────────────────────────────────
    if policy.is_insured:
        for line in lines:
            if line.catalog_id is None:
                continue
            cat_obj = catalog_map.get(line.catalog_id)
            if cat_obj and cat_obj.non_payable:
                # Confidence: high if exact or embedding >= 0.85, else medium
                conf: str
                if line.match_method == "exact" or (line.match_method == "embedding" and (line.match_score or 0) >= 0.85):
                    conf = "high"
                else:
                    conf = "medium"
                eid = f"ev-r3-{uuid.uuid4().hex[:8]}"
                reason = cat_obj.non_payable_reason or (
                    "Commonly listed as non-payable consumable in standard insurer exclusion lists "
                    "(verify against the official list before production use)"
                )
                ev = Evidence(
                    id=eid,
                    type="catalog",
                    text=f"Catalog: '{cat_obj.canonical_name}' — non-payable. {reason}",
                    meta={"catalog_id": line.catalog_id, "ref_source": cat_obj.ref_source or "DEMO_REFERENCE"},
                )
                evidence.append(ev)
                findings.append(Finding(
                    id=f"F-R3-{uuid.uuid4().hex[:8]}",
                    rule_code="R3",
                    kind="coverage",
                    severity="red",
                    origin="rule",
                    line_ids=[line.line_no],
                    title=f"Non-Payable Item — {line.canonical_name or line.raw_text[:30]}",
                    explanation=f"'{line.canonical_name or line.raw_text}' may be deducted by the insurer as a non-payable item.",
                    amount_at_stake=round(line.amount, 2),
                    confidence=conf,  # type: ignore[arg-type]
                    evidence_ids=[eid],
                    uncertain=False,
                ))

    # ── R4 BUNDLED ────────────────────────────────────────────────────────
    for line in lines:
        if line.catalog_id is None:
            continue
        cat_obj = catalog_map.get(line.catalog_id)
        if cat_obj and cat_obj.bundled_in and has_room_line:
            # Only flag 'room_rent' bundled items when there IS a room line
            eid = f"ev-r4-{uuid.uuid4().hex[:8]}"
            ev = Evidence(
                id=eid,
                type="catalog",
                text=f"Catalog: '{cat_obj.canonical_name}' is typically bundled into room rent charges",
                meta={"catalog_id": line.catalog_id, "bundled_in": cat_obj.bundled_in},
            )
            evidence.append(ev)
            findings.append(Finding(
                id=f"F-R4-{uuid.uuid4().hex[:8]}",
                rule_code="R4",
                kind="billing",
                severity="amber",
                origin="rule",
                line_ids=[line.line_no],
                title=f"Possibly Bundled — {line.canonical_name or line.raw_text[:30]}",
                explanation=f"'{line.canonical_name or line.raw_text}' may be included within the room rent. Worth asking whether it should be charged separately.",
                amount_at_stake=round(line.amount, 2),
                confidence="medium",
                evidence_ids=[eid],
                uncertain=True,
            ))

    # ── R5 PRICE VARIANCE ─────────────────────────────────────────────────
    for line in lines:
        if line.catalog_id is None:
            continue
        cat_obj = catalog_map.get(line.catalog_id)
        if not cat_obj or not cat_obj.ref_price_high:
            continue
        # Effective unit price
        if line.unit_price is not None:
            effective_unit = line.unit_price
        elif line.qty and line.qty > 0:
            effective_unit = line.amount / line.qty
        else:
            continue
        threshold = cat_obj.ref_price_high * settings.PRICE_VARIANCE_FACTOR
        if effective_unit > threshold:
            stake = round((effective_unit - cat_obj.ref_price_high) * (line.qty or 1), 2)
            eid = f"ev-r5-{uuid.uuid4().hex[:8]}"
            ev = Evidence(
                id=eid,
                type="catalog",
                text=(
                    f"Catalog reference for '{cat_obj.canonical_name}': ₹{cat_obj.ref_price_low}–₹{cat_obj.ref_price_high} "
                    f"({cat_obj.ref_source or 'DEMO_REFERENCE'}). Charged ₹{effective_unit:.0f}/unit."
                ),
                meta={"catalog_id": line.catalog_id, "ref_source": cat_obj.ref_source or "DEMO_REFERENCE"},
            )
            evidence.append(ev)
            findings.append(Finding(
                id=f"F-R5-{uuid.uuid4().hex[:8]}",
                rule_code="R5",
                kind="billing",
                severity="amber",
                origin="rule",
                line_ids=[line.line_no],
                title=f"Price Worth Asking About — {line.canonical_name or line.raw_text[:30]}",
                explanation=(
                    f"Unit price ₹{effective_unit:.0f} is above the demo reference range "
                    f"(₹{cat_obj.ref_price_low}–₹{cat_obj.ref_price_high}) — "
                    "a reference benchmark, not a legal cap. Worth asking about."
                ),
                amount_at_stake=stake,
                confidence="medium",
                evidence_ids=[eid],
                uncertain=False,
            ))

    # ── R6 ESTIMATE VARIANCE ──────────────────────────────────────────────
    if bill.estimate_amount is not None and bill.stated_total is not None:
        threshold = bill.estimate_amount * settings.ESTIMATE_VARIANCE_FACTOR
        if bill.stated_total > threshold:
            findings.append(Finding(
                id=f"F-R6-{uuid.uuid4().hex[:8]}",
                rule_code="R6",
                kind="billing",
                severity="amber",
                origin="rule",
                line_ids=[],
                title="Final Bill Exceeds Estimate",
                explanation=(
                    f"The final bill (₹{bill.stated_total:,.0f}) exceeds the admission estimate "
                    f"(₹{bill.estimate_amount:,.0f}) by more than {int((settings.ESTIMATE_VARIANCE_FACTOR - 1)*100)}%. "
                    "Worth asking for a detailed explanation."
                ),
                amount_at_stake=None,
                confidence="high",
                evidence_ids=[],
                uncertain=False,
            ))

    return findings, evidence
