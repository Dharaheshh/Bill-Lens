"""
Claim simulator per SPEC §6. Pure Python — no LLM, no DB.
Returns (SimulatorResult, list[Finding]) where the Finding list contains the C1 finding if applicable.
"""
import uuid
from typing import Optional

from app.schemas import (
    Evidence,
    ExtractedBill,
    Finding,
    MatchedLine,
    ResolvedPolicy,
    SimulatorResult,
    WaterfallStep,
)

# Per SPEC §6: categories whose charges are proportionately reduced when room cap is exceeded
ROOM_LINKED = {"room", "nursing", "professional_fee", "procedure"}

_ASSUMPTIONS_BASE = [
    "Estimate based on the terms you confirmed; actual insurer decisions may differ.",
    "Co-pay applied to the admissible amount after deductions.",
]
_ASSUMPTION_PROPORTIONATE = "Proportionate deduction applied to room-linked categories: room, nursing, professional fees, procedures."


def simulate_claim(
    bill: ExtractedBill,
    lines: list[MatchedLine],
    policy: ResolvedPolicy,
    findings: list[Finding],
    catalog_non_payable: set[int] | None = None,
) -> tuple[SimulatorResult, list[Finding]]:
    """
    Run the insurer waterfall simulation.

    Returns:
        (SimulatorResult, new_c1_findings)
        The caller appends new_c1_findings to the findings list.
    """
    if catalog_non_payable is None:
        catalog_non_payable = set()

    steps: list[WaterfallStep] = []
    new_findings: list[Finding] = []
    assumptions = list(_ASSUMPTIONS_BASE)

    # ── STEP 1: billed_total ────────────────────────────────────────────
    billed_total = round(sum(line.amount for line in lines), 2)
    steps.append(WaterfallStep(
        key="billed",
        label="Total Billed",
        amount=billed_total,
        running_total=billed_total,
        explanation="Sum of all line items on the hospital bill.",
    ))

    # ── Uninsured path ──────────────────────────────────────────────────
    if not policy.is_insured:
        steps.append(WaterfallStep(
            key="patient_pays",
            label="You Pay (Self-Pay)",
            amount=billed_total,
            running_total=billed_total,
            explanation="No insurance — patient is responsible for the full amount.",
        ))
        return (
            SimulatorResult(
                applied=False,
                billed_total=billed_total,
                non_payable_total=0.0,
                room_rent_deduction=0.0,
                copay_amount=0.0,
                insurer_pays=0.0,
                patient_pays=billed_total,
                steps=steps,
                assumptions=assumptions,
            ),
            [],
        )

    # ── STEP 2: non_payable_total ───────────────────────────────────────
    # Non-payable = matched lines whose catalog_id is in catalog_non_payable
    non_payable_line_ids: set[int] = set()
    for line in lines:
        if line.catalog_id is not None and line.catalog_id in catalog_non_payable:
            non_payable_line_ids.add(line.line_no)

    # Also include lines flagged R3 in existing findings (belt-and-suspenders)
    for f in findings:
        if f.rule_code == "R3" and not f.dismissed:
            non_payable_line_ids.update(f.line_ids)

    non_payable_total = round(
        sum(line.amount for line in lines if line.line_no in non_payable_line_ids), 2
    )

    running = round(billed_total - non_payable_total, 2)
    if non_payable_total > 0:
        steps.append(WaterfallStep(
            key="non_payable",
            label="Non-Payable Items",
            amount=round(-non_payable_total, 2),
            running_total=running,
            explanation=(
                f"₹{non_payable_total:,.0f} deducted for items typically excluded by insurers "
                "(consumables, hospital-provided toiletries, etc.)."
            ),
        ))

    # ── STEP 3: room_rent_deduction ─────────────────────────────────────
    room_rent_deduction = 0.0
    actual_rent_per_day: Optional[float] = None
    room_line: Optional[MatchedLine] = None

    room_lines = [l for l in lines if l.category == "room" and l.line_no not in non_payable_line_ids]
    if room_lines:
        # Take room line with highest unit_price
        candidate = max(
            room_lines,
            key=lambda l: (l.unit_price or 0) if l.unit_price else (l.amount / max(l.qty or 1, 1)),
        )
        room_line = candidate
        if candidate.unit_price is not None:
            actual_rent_per_day = candidate.unit_price
        elif candidate.qty and candidate.qty > 0:
            actual_rent_per_day = round(candidate.amount / candidate.qty, 2)
        else:
            actual_rent_per_day = candidate.amount

    cap = policy.room_rent_cap_per_day
    if room_line is not None and actual_rent_per_day is not None and cap is not None and actual_rent_per_day > cap:
        ratio = cap / actual_rent_per_day

        if policy.proportionate_deduction:
            # Sum over all ROOM_LINKED lines NOT in non_payable
            linked_total = sum(
                line.amount
                for line in lines
                if (line.category in ROOM_LINKED) and (line.line_no not in non_payable_line_ids)
            )
            room_rent_deduction = round(linked_total * (1 - ratio), 2)
            assumptions.append(_ASSUMPTION_PROPORTIONATE)
        else:
            # Flat cap: only the room line itself
            room_rent_deduction = round(room_line.amount * (1 - ratio), 2)

        running = round(running - room_rent_deduction, 2)
        steps.append(WaterfallStep(
            key="room_rent",
            label="Room Rent Limit",
            amount=round(-room_rent_deduction, 2),
            running_total=running,
            explanation=(
                f"Room at ₹{actual_rent_per_day:,.0f}/day exceeds policy cap of ₹{cap:,.0f}/day "
                f"(ratio {ratio:.4f}). "
                + (
                    f"Proportionate deduction applied to room-linked charges."
                    if policy.proportionate_deduction
                    else "Deduction applied to room charges only."
                )
            ),
        ))

        # C1 finding
        c1_ev_id = f"ev-C1-{uuid.uuid4().hex[:8]}"
        c1_ev = Evidence(
            id=c1_ev_id,
            type="calc",
            text=(
                f"Room rent cap: ₹{cap:,.0f}/day. Actual: ₹{actual_rent_per_day:,.0f}/day. "
                f"Ratio = {cap}/{actual_rent_per_day:.0f} = {ratio:.4f}. "
                f"Deduction = ₹{room_rent_deduction:,.0f}."
            ),
            meta={"ratio": ratio, "cap": cap, "actual": actual_rent_per_day},
        )
        c1_finding = Finding(
            id=f"F-C1-{uuid.uuid4().hex[:8]}",
            rule_code="C1",
            kind="coverage",
            severity="red",
            origin="rule",
            line_ids=[],
            title="Room Rent Limit May Reduce Claim",
            explanation=(
                f"Your room at ₹{actual_rent_per_day:,.0f}/day exceeds the policy cap of ₹{cap:,.0f}/day. "
                f"Insurer may deduct ₹{room_rent_deduction:,.0f} from the claim."
            ),
            amount_at_stake=room_rent_deduction,
            confidence="high",
            evidence_ids=[c1_ev_id],
            uncertain=False,
        )
        # Store evidence on finding for caller to handle
        c1_finding._c1_evidence = c1_ev  # type: ignore[attr-defined]
        new_findings.append(c1_finding)

    # ── admissible ──────────────────────────────────────────────────────
    admissible = round(billed_total - non_payable_total - room_rent_deduction, 2)

    # ── STEP 4: copay ───────────────────────────────────────────────────
    copay_amount = 0.0
    if policy.copay_pct and policy.copay_pct > 0:
        copay_amount = round(admissible * policy.copay_pct / 100.0, 2)
        running = round(admissible - copay_amount, 2)
        steps.append(WaterfallStep(
            key="copay",
            label=f"Co-pay ({policy.copay_pct:.0f}%)",
            amount=round(-copay_amount, 2),
            running_total=running,
            explanation=f"{policy.copay_pct:.0f}% co-payment applied to admissible amount of ₹{admissible:,.0f}.",
        ))
    else:
        running = admissible

    # ── STEP 5: insurer_pays (sum insured cap) ──────────────────────────
    insurer_pays = running

    if policy.sum_insured is not None and insurer_pays > policy.sum_insured:
        over = round(insurer_pays - policy.sum_insured, 2)
        insurer_pays = policy.sum_insured
        running = insurer_pays
        steps.append(WaterfallStep(
            key="sum_insured_cap",
            label="Sum Insured Limit",
            amount=round(-over, 2),
            running_total=running,
            explanation=f"Insurer liability capped at sum insured ₹{policy.sum_insured:,.0f}.",
        ))

    insurer_pays = round(insurer_pays, 2)

    # ── STEP 6: patient_pays ────────────────────────────────────────────
    patient_pays = round(billed_total - insurer_pays, 2)

    steps.append(WaterfallStep(
        key="insurer_pays",
        label="Insurer Likely Pays",
        amount=insurer_pays,
        running_total=insurer_pays,
        explanation="Estimated insurer payout after all deductions.",
    ))
    steps.append(WaterfallStep(
        key="patient_pays",
        label="You Pay",
        amount=patient_pays,
        running_total=patient_pays,
        explanation="Your estimated out-of-pocket cost (non-payables + co-pay + any amount over sum insured).",
    ))

    return (
        SimulatorResult(
            applied=True,
            billed_total=billed_total,
            non_payable_total=non_payable_total,
            room_rent_deduction=room_rent_deduction,
            copay_amount=copay_amount,
            insurer_pays=insurer_pays,
            patient_pays=patient_pays,
            steps=steps,
            assumptions=assumptions,
        ),
        new_findings,
    )
