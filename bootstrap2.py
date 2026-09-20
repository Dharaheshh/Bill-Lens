import os
import json

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# rules.py
rules_py = '''import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import CatalogItem
from app.schemas import Evidence, ExtractedBill, Finding, MatchedLine, ResolvedPolicy
import logging
from app.config import settings

logger = logging.getLogger(__name__)

async def apply_rules(
    session: AsyncSession,
    bill: ExtractedBill,
    lines: list[MatchedLine],
    policy: ResolvedPolicy,
) -> tuple[list[Finding], list[Evidence]]:
    findings = []
    evidence = []
    
    catalog_map = {}
    if any(l.catalog_id for l in lines):
        ids = [l.catalog_id for l in lines if l.catalog_id]
        res = await session.execute(select(CatalogItem).where(CatalogItem.id.in_(ids)))
        catalog_map = {item.id: item for item in res.scalars()}
        
    bill_level_r1_diff = 0.0
    expected_total = sum(l.amount for l in lines if l.amount is not None)
    if bill.stated_total is not None and abs(expected_total - bill.stated_total) > 1.0:
        fid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        evidence.append(Evidence(id=eid, type="line", text=f"Sum of lines {expected_total} != stated total {bill.stated_total}"))
        findings.append(Finding(
            id=fid, rule_code="R1", kind="billing", severity="red", origin="rule",
            line_ids=[], title="Arithmetic Error",
            explanation="Sum of lines does not match stated total.",
            amount_at_stake=abs(expected_total - bill.stated_total), confidence="high", evidence_ids=[]
        ))
        
    for line in lines:
        if line.qty is not None and line.unit_price is not None:
            expected = line.qty * line.unit_price
            if abs(expected - line.amount) > 1.0:
                fid = str(uuid.uuid4())
                eid = str(uuid.uuid4())
                evidence.append(Evidence(id=eid, type="line", text=f"{line.qty} x {line.unit_price} = {expected} != {line.amount}"))
                findings.append(Finding(
                    id=fid, rule_code="R1", kind="billing", severity="red", origin="rule",
                    line_ids=[line.line_no], title="Arithmetic Error",
                    explanation="Qty x Price does not match Amount.",
                    amount_at_stake=abs(expected - line.amount), confidence="high", evidence_ids=[]
                ))
                
    groups = {}
    for line in lines:
        c_id = line.catalog_id if line.catalog_id else (line.canonical_name or line.raw_text).strip().lower()
        key = (c_id, line.service_date)
        groups.setdefault(key, []).append(line)
        
    for key, group_lines in groups.items():
        if len(group_lines) <= 1:
            continue
            
        c_id = group_lines[0].catalog_id
        cat = catalog_map.get(c_id) if c_id else None
        category = group_lines[0].category
        
        if category in {"investigation", "procedure", "professional_fee", "nursing", "room"}:
            max_per = cat.max_per_day if cat and cat.max_per_day is not None else 1
            if len(group_lines) > max_per:
                extra_lines = sorted(group_lines, key=lambda x: x.amount, reverse=True)[max_per:]
                for el in extra_lines:
                    fid = str(uuid.uuid4())
                    findings.append(Finding(
                        id=fid, rule_code="R2", kind="billing", severity="red", origin="rule",
                        line_ids=[el.line_no], title="Duplicate Charge",
                        explanation=f"Exceeds max {max_per} per day.",
                        amount_at_stake=el.amount, confidence="high", evidence_ids=[]
                    ))
        elif category in {"pharmacy", "consumable"}:
            # check same qty and amount
            seen = {}
            for l in group_lines:
                k = (l.qty, l.amount)
                if k in seen:
                    fid = str(uuid.uuid4())
                    findings.append(Finding(
                        id=fid, rule_code="R2", kind="billing", severity="amber", origin="rule",
                        line_ids=[seen[k].line_no, l.line_no], title="Possible Duplicate",
                        explanation="Multiple items with same qty and amount on same day.",
                        amount_at_stake=l.amount, confidence="medium", uncertain=True, evidence_ids=[]
                    ))
                else:
                    seen[k] = l

    if policy.is_insured:
        for line in lines:
            if line.catalog_id and catalog_map.get(line.catalog_id, CatalogItem()).non_payable:
                fid = str(uuid.uuid4())
                eid = str(uuid.uuid4())
                evidence.append(Evidence(id=eid, type="catalog", text="Item is non-payable."))
                conf = "high" if line.match_method == "exact" or (line.match_method == "embedding" and (line.match_score or 0) >= 0.85) else "medium"
                findings.append(Finding(
                    id=fid, rule_code="R3", kind="coverage", severity="red", origin="rule",
                    line_ids=[line.line_no], title="Non-Payable Item",
                    explanation=f"{line.canonical_name or line.raw_text} is non-payable.",
                    amount_at_stake=line.amount, confidence=conf, evidence_ids=[]
                ))
                
    for line in lines:
        if line.catalog_id and line.catalog_id in catalog_map:
            cat = catalog_map[line.catalog_id]
            if cat.bundled_in == "room_rent" and any(l.category == "room" for l in lines):
                fid = str(uuid.uuid4())
                findings.append(Finding(
                    id=fid, rule_code="R4", kind="billing", severity="amber", origin="rule",
                    line_ids=[line.line_no], title="Bundled Charge",
                    explanation=f"{line.canonical_name or line.raw_text} is typically bundled in room rent.",
                    amount_at_stake=line.amount, confidence="medium", uncertain=True, evidence_ids=[]
                ))
                
    for line in lines:
        if line.catalog_id and line.catalog_id in catalog_map:
            cat = catalog_map[line.catalog_id]
            if cat.ref_price_high:
                eff_price = line.unit_price if line.unit_price else (line.amount / line.qty if line.qty else line.amount)
                if eff_price > cat.ref_price_high * settings.PRICE_VARIANCE_FACTOR:
                    fid = str(uuid.uuid4())
                    diff = (eff_price - cat.ref_price_high) * (line.qty or 1)
                    findings.append(Finding(
                        id=fid, rule_code="R5", kind="billing", severity="amber", origin="rule",
                        line_ids=[line.line_no], title="Price Variance",
                        explanation=f"Unit price exceeds the demo reference range (a reference benchmark, not a legal cap).",
                        amount_at_stake=diff, confidence="medium", evidence_ids=[]
                    ))
                    
    if bill.estimate_amount and bill.stated_total:
        if bill.stated_total > bill.estimate_amount * settings.ESTIMATE_VARIANCE_FACTOR:
            fid = str(uuid.uuid4())
            findings.append(Finding(
                id=fid, rule_code="R6", kind="billing", severity="amber", origin="rule",
                line_ids=[], title="Estimate Variance",
                explanation=f"Stated total exceeds estimate by >{(settings.ESTIMATE_VARIANCE_FACTOR-1)*100}%.",
                amount_at_stake=None, confidence="high", evidence_ids=[]
            ))
            
    return findings, evidence
'''
write_file("backend/app/engine/rules.py", rules_py)
print("Rules done.")
