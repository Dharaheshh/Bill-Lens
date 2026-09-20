import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

simulator_py = '''import uuid
from app.schemas import ExtractedBill, Finding, MatchedLine, ResolvedPolicy, SimulatorResult
import logging

logger = logging.getLogger(__name__)

def simulate_claim(
    bill: ExtractedBill,
    lines: list[MatchedLine],
    policy: ResolvedPolicy,
    findings: list[Finding],
    catalog_non_payable: set[int],
) -> tuple[SimulatorResult, list[Finding]]:
    new_findings = []
    
    billed_total = sum(l.amount for l in lines)
    non_payable_total = sum(l.amount for l in lines if l.catalog_id in catalog_non_payable)
    non_payable_ids = {l.line_no for l in lines if l.catalog_id in catalog_non_payable}
    
    room_lines = [l for l in lines if l.category == "room"]
    actual_rent = 0
    days = 1
    if room_lines:
        with_price = [l for l in room_lines if l.unit_price is not None]
        if with_price:
            best = max(with_price, key=lambda x: x.unit_price)
            actual_rent = best.unit_price
            days = best.qty or 1
        else:
            best = max(room_lines, key=lambda x: x.amount)
            actual_rent = best.amount
            days = best.qty or 1
            logger.warning("No unit_price on room lines; using amount as proxy.")
            
    room_rent_deduction = 0.0
    cap = policy.room_rent_cap
    proportionate = policy.proportionate_deduction
    
    if cap and actual_rent > cap:
        ratio = cap / actual_rent
        if proportionate:
            room_linked_cats = {"room", "nursing", "professional_fee", "procedure"}
            target_amount = sum(l.amount for l in lines if l.category in room_linked_cats and l.line_no not in non_payable_ids)
            room_rent_deduction = target_amount * (1 - ratio)
        else:
            room_rent_deduction = sum(l.amount for l in room_lines if l.line_no not in non_payable_ids) * (1 - ratio)
            
        new_findings.append(Finding(
            id=str(uuid.uuid4()), rule_code="C1", kind="coverage", severity="red", origin="rule",
            line_ids=[], title="Room Rent Limit May Reduce Claim",
            explanation=f"Your room at ₹{actual_rent:,.0f}/day exceeds the policy cap of ₹{cap:,.0f}/day. Insurer may deduct ₹{room_rent_deduction:,.0f} from the claim.",
            amount_at_stake=room_rent_deduction, evidence_ids=[]
        ))

    admissible = billed_total - non_payable_total - room_rent_deduction
    copay_amount = round(admissible * (policy.copay_pct or 0) / 100, 2)
    insurer_pays = round(admissible - copay_amount, 2)
    
    if policy.sum_insured and insurer_pays > policy.sum_insured:
        insurer_pays = float(policy.sum_insured)
        
    patient_pays = round(billed_total - insurer_pays, 2)
    
    assumptions = [
        "Estimate based on the terms you confirmed; actual insurer decisions may differ.",
        "Co-pay applied to the admissible amount after deductions."
    ]
    if room_rent_deduction > 0 and proportionate:
        assumptions.append("Proportionate deduction applied to room-linked categories: room, nursing, professional fees, procedures.")
        
    return SimulatorResult(
        billed_total=billed_total,
        non_payable_total=non_payable_total,
        room_rent_deduction=room_rent_deduction,
        copay_amount=copay_amount,
        insurer_pays=insurer_pays,
        patient_pays=patient_pays,
        assumptions=assumptions
    ), new_findings
'''
write_file("backend/app/engine/simulator.py", simulator_py)

totals_py = '''from app.schemas import ExtractedBill, Finding, SimulatorResult, Summary

def calculate_summary(
    bill: ExtractedBill,
    findings: list[Finding],
    simulator: SimulatorResult,
) -> Summary:
    active = [f for f in findings if not f.dismissed]
    
    line_max = {}
    bill_level_r1 = 0.0
    for f in active:
        if f.kind != 'billing' or f.rule_code == 'R6':
            continue
        if not f.line_ids:
            if f.amount_at_stake:
                bill_level_r1 = max(bill_level_r1, f.amount_at_stake)
        else:
            for lid in f.line_ids:
                if f.amount_at_stake is not None:
                    line_max[lid] = max(line_max.get(lid, 0.0), f.amount_at_stake)
                    
    questionable_total = round(sum(line_max.values()) + bill_level_r1, 2)
    insurer_deductions_total = round(simulator.non_payable_total + simulator.room_rent_deduction, 2)
    
    counts = {'red': 0, 'amber': 0, 'info': 0}
    for f in active:
        counts[f.severity] = counts.get(f.severity, 0) + 1
        
    return Summary(
        billed_total=simulator.billed_total,
        questionable_total=questionable_total,
        insurer_deductions_total=insurer_deductions_total,
        insurer_pays=simulator.insurer_pays,
        patient_pays=simulator.patient_pays,
        counts=counts,
        agent_stats={}
    )
'''
write_file("backend/app/engine/totals.py", totals_py)
'''
