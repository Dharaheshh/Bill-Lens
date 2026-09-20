import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogItem
from app.schemas import Evidence, ExtractedBill, Finding, MatchedLine, ResolvedPolicy


async def apply_rules(session: AsyncSession, bill: ExtractedBill, lines: list[MatchedLine], policy: ResolvedPolicy) -> tuple[list[Finding], list[Evidence]]:
    findings = []
    evidence = []
    
    # Pre-fetch catalog info for matched lines
    catalog_ids = [l.catalog_id for l in lines if l.catalog_id]
    catalog_map = {}
    if catalog_ids:
        stmt = select(CatalogItem).where(CatalogItem.id.in_(catalog_ids))
        res = await session.execute(stmt)
        for item in res.scalars():
            catalog_map[item.id] = item
            
    # R1: Arithmetic
    for line in lines:
        if line.qty is not None and line.unit_price is not None:
            expected = line.qty * line.unit_price
            if abs(expected - line.amount) > 1.0:
                fid = str(uuid.uuid4())
                eid = str(uuid.uuid4())
                evidence.append(Evidence(id=eid, type="calc", text=f"{line.qty} x {line.unit_price} = {expected} != {line.amount}"))
                findings.append(Finding(
                    id=fid, rule_code="R1", kind="billing", severity="red", origin="rule",
                    line_ids=[line.line_no], title="Arithmetic Error",
                    explanation="Qty x Price does not match Amount.",
                    amount_at_stake=abs(expected - line.amount), confidence="high", evidence_ids=[eid]
                ))

    # R2: Duplicate
    seen = {}
    for line in lines:
        if not line.canonical_name: continue
        key = (line.canonical_name, line.service_date, line.amount)
        if key in seen:
            fid = str(uuid.uuid4())
            findings.append(Finding(
                id=fid, rule_code="R2", kind="billing", severity="red", origin="rule",
                line_ids=[seen[key], line.line_no], title="Duplicate Charge",
                explanation=f"Identical charge for {line.canonical_name} on same day.",
                amount_at_stake=line.amount, confidence="high", evidence_ids=[]
            ))
        else:
            seen[key] = line.line_no

    # R3: Non-payable
    for line in lines:
        if line.catalog_id and line.catalog_id in catalog_map:
            cat = catalog_map[line.catalog_id]
            if cat.non_payable:
                fid = str(uuid.uuid4())
                eid = str(uuid.uuid4())
                evidence.append(Evidence(id=eid, type="catalog", text=cat.non_payable_reason or "Non-payable per standard catalog."))
                findings.append(Finding(
                    id=fid, rule_code="R3", kind="coverage", severity="red", origin="rule",
                    line_ids=[line.line_no], title="Non-Payable Item",
                    explanation=f"{line.canonical_name} is marked as non-payable.",
                    amount_at_stake=line.amount, confidence="high", evidence_ids=[eid]
                ))

    # R4: Bundled
    for line in lines:
        if line.catalog_id and line.catalog_id in catalog_map:
            cat = catalog_map[line.catalog_id]
            if cat.bundled_in:
                # Check if bundled parent exists in bill
                if any(l.category == cat.bundled_in for l in lines):
                    fid = str(uuid.uuid4())
                    findings.append(Finding(
                        id=fid, rule_code="R4", kind="billing", severity="amber", origin="rule",
                        line_ids=[line.line_no], title="Bundled Charge",
                        explanation=f"{line.canonical_name} is usually bundled in {cat.bundled_in}.",
                        amount_at_stake=line.amount, confidence="medium", evidence_ids=[]
                    ))
                    
    # R5: Price Variance
    from app.config import settings
    for line in lines:
        if line.catalog_id and line.catalog_id in catalog_map:
            cat = catalog_map[line.catalog_id]
            if cat.ref_price_high and line.unit_price:
                max_allowed = cat.ref_price_high * settings.PRICE_VARIANCE_FACTOR
                if line.unit_price > max_allowed:
                    fid = str(uuid.uuid4())
                    findings.append(Finding(
                        id=fid, rule_code="R5", kind="billing", severity="amber", origin="rule",
                        line_ids=[line.line_no], title="Price Variance",
                        explanation=f"Unit price {line.unit_price} exceeds reference benchmark ({cat.ref_price_high}).",
                        amount_at_stake=(line.unit_price - cat.ref_price_high) * (line.qty or 1), 
                        confidence="medium", evidence_ids=[]
                    ))

    # R6: Estimate Variance
    if bill.estimate_amount and bill.stated_total:
        max_est = bill.estimate_amount * settings.ESTIMATE_VARIANCE_FACTOR
        if bill.stated_total > max_est:
            fid = str(uuid.uuid4())
            findings.append(Finding(
                id=fid, rule_code="R6", kind="billing", severity="amber", origin="rule",
                line_ids=[], title="Estimate Exceeded",
                explanation=f"Total {bill.stated_total} exceeds estimate {bill.estimate_amount} by >20%.",
                amount_at_stake=bill.stated_total - bill.estimate_amount, confidence="high", evidence_ids=[]
            ))
            
    return findings, evidence
