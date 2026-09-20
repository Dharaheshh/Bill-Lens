from app.engine.simulator import simulate_claim
from app.schemas import ExtractedBill, MatchedLine, ResolvedPolicy


def test_simulator_proportionate_true():
    bill = ExtractedBill(lines=[], stated_total=122000)
    lines = [
        MatchedLine(line_no=1, raw_text="Room", amount=20000, category="room", unit_price=20000, qty=1),
        MatchedLine(line_no=2, raw_text="Surgery", amount=20000, category="procedure"),
        MatchedLine(line_no=3, raw_text="Pharmacy", amount=80000, category="pharmacy"),
        MatchedLine(line_no=4, raw_text="Gloves", amount=2000, category="consumable")
    ]
    policy = ResolvedPolicy(is_insured=True, room_rent_cap_per_day=5000, proportionate_deduction=True, copay_pct=10)
    
    # Mock finding for R3 non-payable (Gloves)
    from app.schemas import Finding
    findings = [Finding(id="f1", rule_code="R3", kind="coverage", severity="red", origin="rule", line_ids=[4], title="Non-payable", explanation="", amount_at_stake=2000, confidence="high")]
    
    result = simulate_claim(bill, lines, policy, findings)
    
    assert result.non_payable_total == 2000
    assert result.room_rent_deduction == 30000 # 15k room + 15k linked surgery
    assert result.copay_amount == 9000 # 10% of 90k
    assert result.insurer_pays == 81000
    assert result.patient_pays == 41000

def test_simulator_proportionate_false():
    bill = ExtractedBill(lines=[], stated_total=122000)
    lines = [
        MatchedLine(line_no=1, raw_text="Room", amount=20000, category="room", unit_price=20000, qty=1),
        MatchedLine(line_no=2, raw_text="Surgery", amount=20000, category="procedure"),
        MatchedLine(line_no=3, raw_text="Pharmacy", amount=80000, category="pharmacy"),
        MatchedLine(line_no=4, raw_text="Gloves", amount=2000, category="consumable")
    ]
    policy = ResolvedPolicy(is_insured=True, room_rent_cap_per_day=5000, proportionate_deduction=False, copay_pct=10)
    
    from app.schemas import Finding
    findings = [Finding(id="f1", rule_code="R3", kind="coverage", severity="red", origin="rule", line_ids=[4], title="Non-payable", explanation="", amount_at_stake=2000, confidence="high")]
    
    result = simulate_claim(bill, lines, policy, findings)
    
    assert result.room_rent_deduction == 15000 # Only room deduction, no linked
    assert result.copay_amount == 10500 # 10% of 105k
    assert result.insurer_pays == 94500
    assert result.patient_pays == 27500
