from app.schemas import (
    ExtractedBill,
    Finding,
    MatchedLine,
    ResolvedPolicy,
    SimulatorResult,
    WaterfallStep,
)


def simulate_claim(bill: ExtractedBill, lines: list[MatchedLine], policy: ResolvedPolicy, findings: list[Finding]) -> SimulatorResult:
    steps = []
    
    billed = bill.stated_total if bill.stated_total else sum(l.amount for l in lines)
    steps.append(WaterfallStep(key="billed", label="Total Billed", amount=billed, running_total=billed, explanation="Initial hospital bill total"))
    
    if not policy.is_insured:
        return SimulatorResult(
            applied=False, billed_total=billed, non_payable_total=0, room_rent_deduction=0,
            copay_amount=0, insurer_pays=0, patient_pays=billed, steps=steps
        )

    # Non-payable
    non_payable_line_ids = set()
    for f in findings:
        if f.rule_code == "R3" and not f.dismissed:
            non_payable_line_ids.update(f.line_ids)
            
    non_payable = sum(l.amount for l in lines if l.line_no in non_payable_line_ids)
    admissible = billed - non_payable
    if non_payable > 0:
        steps.append(WaterfallStep(key="non_payable", label="Non-Payable Items", amount=-non_payable, running_total=admissible, explanation="Deducted per standard exclusions"))

    # Room Rent
    room_lines = [l for l in lines if l.category == "room" and l.line_no not in non_payable_line_ids]
    room_rent_deduction = 0
    ratio = 1.0
    
    if room_lines and policy.room_rent_cap_per_day:
        actual_room_rent_per_day = max((l.unit_price for l in room_lines if l.unit_price), default=0)
        if actual_room_rent_per_day == 0:
            qty = sum(l.qty for l in room_lines if l.qty) or 1
            actual_room_rent_per_day = sum(l.amount for l in room_lines) / qty
            
        cap = policy.room_rent_cap_per_day
        if actual_room_rent_per_day > cap:
            excess_per_day = actual_room_rent_per_day - cap
            days = sum(l.qty for l in room_lines if l.qty) or 1
            room_deduction = excess_per_day * days
            room_rent_deduction += room_deduction
            
            if policy.proportionate_deduction:
                ratio = cap / actual_room_rent_per_day
                linked_categories = {"nursing", "professional_fee", "procedure"}
                linked_lines = [l for l in lines if l.category in linked_categories and l.line_no not in non_payable_line_ids]
                linked_total = sum(l.amount for l in linked_lines)
                proportionate_ded = linked_total * (1 - ratio)
                room_rent_deduction += proportionate_ded
                
    if room_rent_deduction > 0:
        admissible -= room_rent_deduction
        steps.append(WaterfallStep(key="room_rent", label="Room Rent Limit", amount=-room_rent_deduction, running_total=admissible, explanation="Capped room rent and linked charges"))

    # Copay
    copay_amount = admissible * (policy.copay_pct / 100.0) if policy.copay_pct else 0
    if copay_amount > 0:
        admissible -= copay_amount
        steps.append(WaterfallStep(key="copay", label=f"Co-pay ({policy.copay_pct}%)", amount=-copay_amount, running_total=admissible, explanation="Patient co-payment share"))

    # Sum Insured
    insurer_pays = admissible
    if policy.sum_insured and insurer_pays > policy.sum_insured:
        insurer_pays = policy.sum_insured
        steps.append(WaterfallStep(key="sum_insured_cap", label="Sum Insured Limit", amount=-(admissible - insurer_pays), running_total=insurer_pays, explanation="Capped at maximum sum insured"))

    patient_pays = billed - insurer_pays

    return SimulatorResult(
        applied=True,
        billed_total=billed,
        non_payable_total=non_payable,
        room_rent_deduction=room_rent_deduction,
        copay_amount=copay_amount,
        insurer_pays=insurer_pays,
        patient_pays=patient_pays,
        steps=steps,
        assumptions=["Standard deductions applied correctly"]
    )
