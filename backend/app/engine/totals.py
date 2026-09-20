"""
Summary totals per SPEC §5.7.
Pure Python — no LLM, no DB.
"""
from app.schemas import ExtractedBill, Finding, SimulatorResult, Summary


def calculate_summary(
    bill: ExtractedBill,
    findings: list[Finding],
    simulator: SimulatorResult,
) -> Summary:
    """
    questionable_total: billing findings not dismissed, max amount_at_stake per LINE (deduped).
    Bill-level R1 (line_ids=[]) counted once. R6 excluded (see SPEC §5.7).
    insurer_deductions_total: non_payable_total + room_rent_deduction from simulator.
    """
    active = [f for f in findings if not f.dismissed]

    # Build per-line max for billing findings
    line_max: dict[int, float] = {}
    bill_level_r1_total = 0.0

    for f in active:
        if f.kind != "billing":
            continue
        if f.rule_code == "R6":
            # R6 is bill-level, excluded from questionable_total
            continue
        if f.amount_at_stake is None:
            continue
        if not f.line_ids:
            # Bill-level R1
            bill_level_r1_total = max(bill_level_r1_total, f.amount_at_stake)
        else:
            for lid in f.line_ids:
                line_max[lid] = max(line_max.get(lid, 0.0), f.amount_at_stake)

    questionable_total = round(sum(line_max.values()) + bill_level_r1_total, 2)

    # Insurer deductions = non_payable + room_rent (both coverage kind)
    insurer_deductions_total = round(
        simulator.non_payable_total + simulator.room_rent_deduction, 2
    )

    # Counts of non-dismissed findings
    counts: dict[str, int] = {"red": 0, "amber": 0, "info": 0}
    for f in active:
        sev = f.severity
        counts[sev] = counts.get(sev, 0) + 1

    return Summary(
        billed_total=simulator.billed_total,
        questionable_total=questionable_total,
        insurer_deductions_total=insurer_deductions_total,
        insurer_pays=simulator.insurer_pays,
        patient_pays=simulator.patient_pays,
        counts=counts,
        agent_stats={},
    )
