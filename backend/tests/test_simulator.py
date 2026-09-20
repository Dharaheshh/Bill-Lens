"""
test_simulator.py — SPEC §6 worked examples must pass exactly.
Both Example 1 and Example 2 verified below.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.schemas import (
    BillLine, ExtractedBill, MatchedLine, ResolvedPolicy, SimulatorResult
)
from app.engine.simulator import simulate_claim


def make_spec_lines():
    """Exact 5 lines from SPEC §6 worked example."""
    return [
        MatchedLine(
            line_no=1, raw_text="ROOM RENT", qty=5.0, unit_price=8000.0, amount=40000.0,
            category="room", catalog_id=1, canonical_name="ROOM RENT",
            match_method="exact", match_score=1.0
        ),
        MatchedLine(
            line_no=2, raw_text="SURGEON FEE", amount=40000.0,
            category="professional_fee", catalog_id=2, canonical_name="SURGEON FEE",
            match_method="exact", match_score=1.0
        ),
        MatchedLine(
            line_no=3, raw_text="PHARMACY", amount=30000.0,
            category="pharmacy", catalog_id=3, canonical_name="PHARMACY",
            match_method="exact", match_score=1.0
        ),
        MatchedLine(
            line_no=4, raw_text="NON-PAYABLE CONSUMABLES", amount=2000.0,
            category="consumable", catalog_id=4, canonical_name="NON-PAYABLE CONSUMABLES",
            match_method="exact", match_score=1.0
        ),
        MatchedLine(
            line_no=5, raw_text="INVESTIGATIONS", amount=10000.0,
            category="investigation", catalog_id=5, canonical_name="INVESTIGATIONS",
            match_method="exact", match_score=1.0
        ),
    ]


def make_bill(lines):
    total = sum(l.amount for l in lines)
    return ExtractedBill(hospital_name="Demo Hospital", stated_total=total, lines=[])


# ─── Example 1: proportionate=True ──────────────────────────────────────────
def test_example1_proportionate():
    """
    SPEC §6 Example 1:
    room 5×8000=40000; surgeon_fee 40000; pharmacy 30000; non-payable 2000; investigations 10000
    cap=5000/day; proportionate=True; copay=10%
    → billed=122000; non_payable=2000; ratio=0.625; room_linked=80000 (room+prof_fee only, no nursing in this example)
      deduction=80000*(1-0.625)=30000; admissible=90000; copay=9000; insurer=81000; patient=41000
    """
    lines = make_spec_lines()
    bill = make_bill(lines)
    policy = ResolvedPolicy(
        is_insured=True,
        sum_insured=500000.0,
        room_rent_cap_per_day=5000.0,
        copay_pct=10.0,
        proportionate_deduction=True,
    )
    catalog_non_payable = {4}  # catalog_id=4 is non-payable

    result, c1_findings = simulate_claim(bill, lines, policy, [], catalog_non_payable)

    assert result.applied is True
    assert result.billed_total == 122000.0, f"billed_total={result.billed_total}"
    assert result.non_payable_total == 2000.0, f"non_payable_total={result.non_payable_total}"
    # ROOM_LINKED lines not non-payable: room(40000) + professional_fee(40000) = 80000
    # deduction = 80000 * (1 - 5000/8000) = 80000 * 0.375 = 30000
    assert result.room_rent_deduction == 30000.0, f"room_rent_deduction={result.room_rent_deduction}"
    assert result.copay_amount == 9000.0, f"copay_amount={result.copay_amount}"
    assert result.insurer_pays == 81000.0, f"insurer_pays={result.insurer_pays}"
    assert result.patient_pays == 41000.0, f"patient_pays={result.patient_pays}"
    assert len(c1_findings) == 1
    assert c1_findings[0].rule_code == "C1"
    assert c1_findings[0].amount_at_stake == 30000.0


# ─── Example 2: proportionate=False ─────────────────────────────────────────
def test_example2_flat_cap():
    """
    SPEC §6 Example 2 (same but proportionate=False):
    deduction = room_line.amount * (1 - ratio) = 40000 * 0.375 = 15000
    admissible=105000; copay=10500; insurer=94500; patient=27500
    """
    lines = make_spec_lines()
    bill = make_bill(lines)
    policy = ResolvedPolicy(
        is_insured=True,
        sum_insured=500000.0,
        room_rent_cap_per_day=5000.0,
        copay_pct=10.0,
        proportionate_deduction=False,
    )
    catalog_non_payable = {4}

    result, c1_findings = simulate_claim(bill, lines, policy, [], catalog_non_payable)

    assert result.billed_total == 122000.0
    assert result.non_payable_total == 2000.0
    assert result.room_rent_deduction == 15000.0, f"room_rent_deduction={result.room_rent_deduction}"
    assert result.copay_amount == 10500.0, f"copay_amount={result.copay_amount}"
    assert result.insurer_pays == 94500.0, f"insurer_pays={result.insurer_pays}"
    assert result.patient_pays == 27500.0, f"patient_pays={result.patient_pays}"


# ─── Uninsured path ─────────────────────────────────────────────────────────
def test_uninsured():
    lines = make_spec_lines()
    bill = make_bill(lines)
    policy = ResolvedPolicy(is_insured=False)

    result, c1_findings = simulate_claim(bill, lines, policy, [], set())

    assert result.applied is False
    assert result.insurer_pays == 0.0
    assert result.patient_pays == 122000.0
    assert len(c1_findings) == 0


# ─── No room cap (cap not exceeded) ─────────────────────────────────────────
def test_no_room_deduction_when_under_cap():
    lines = make_spec_lines()
    bill = make_bill(lines)
    policy = ResolvedPolicy(
        is_insured=True,
        room_rent_cap_per_day=10000.0,  # Higher than 8000 → no deduction
        copay_pct=0.0,
        proportionate_deduction=True,
    )
    catalog_non_payable = {4}

    result, c1_findings = simulate_claim(bill, lines, policy, [], catalog_non_payable)

    assert result.room_rent_deduction == 0.0
    assert result.insurer_pays == 120000.0  # 122000 - 2000 non-payable
    assert result.patient_pays == 2000.0
    assert len(c1_findings) == 0


# ─── Sum insured cap ────────────────────────────────────────────────────────
def test_sum_insured_cap():
    lines = [
        MatchedLine(
            line_no=1, raw_text="SURGERY", amount=600000.0,
            category="procedure", catalog_id=1, canonical_name="SURGERY",
            match_method="exact", match_score=1.0
        )
    ]
    bill = make_bill(lines)
    policy = ResolvedPolicy(
        is_insured=True,
        sum_insured=500000.0,
        copay_pct=0.0,
        proportionate_deduction=False,
    )

    result, _ = simulate_claim(bill, lines, policy, [], set())

    assert result.insurer_pays == 500000.0
    assert result.patient_pays == 100000.0
