import uuid
from datetime import date

from fastapi import APIRouter, Response

from app.schemas import (
    ActionPack,
    BillLine,
    DeskQuestion,
    Evidence,
    ExtractedBill,
    Finding,
    Letter,
    MatchedLine,
    PolicyTerm,
    ResolvedPolicy,
    RunConfirmRequest,
    RunCreateRequest,
    RunCreateResponse,
    RunResult,
    RunStatusResponse,
    SimulatorResult,
    Summary,
    TraceEvent,
    WaterfallStep,
)

router = APIRouter()


def _example_run_result(run_id: str) -> RunResult:
    lines = [
        MatchedLine(
            line_no=1,
            raw_text="ROOM RENT",
            qty=5,
            unit_price=8000,
            amount=40000,
            service_date=date(2024, 1, 1),
            category_guess="room",
            catalog_id=1,
            canonical_name="ROOM RENT",
            category="room",
            match_method="exact",
            match_score=1.0,
        ),
        MatchedLine(
            line_no=2,
            raw_text="NURSING CHARGES",
            qty=5,
            unit_price=800,
            amount=4000,
            service_date=date(2024, 1, 1),
            category_guess="nursing",
            catalog_id=4,
            canonical_name="NURSING CHARGES",
            category="nursing",
            match_method="exact",
            match_score=1.0,
        ),
        MatchedLine(
            line_no=3,
            raw_text="SURGEON FEE",
            qty=1,
            unit_price=40000,
            amount=40000,
            service_date=date(2024, 1, 3),
            category_guess="professional_fee",
            catalog_id=6,
            canonical_name="SURGEON FEE",
            category="professional_fee",
            match_method="exact",
            match_score=1.0,
        ),
        MatchedLine(
            line_no=4,
            raw_text="INJ PANTOP 40MG",
            qty=5,
            unit_price=120,
            amount=600,
            service_date=date(2024, 1, 1),
            category_guess="pharmacy",
            catalog_id=30,
            canonical_name="PANTOPRAZOLE INJECTION 40MG",
            category="pharmacy",
            match_method="embedding",
            match_score=0.91,
        ),
        MatchedLine(
            line_no=5,
            raw_text="SURGICAL GLOVES",
            qty=10,
            unit_price=50,
            amount=500,
            service_date=date(2024, 1, 3),
            category_guess="consumable",
            catalog_id=50,
            canonical_name="SURGICAL GLOVES",
            category="consumable",
            match_method="exact",
            match_score=1.0,
        ),
        MatchedLine(
            line_no=6,
            raw_text="PHARMACY",
            qty=1,
            unit_price=30000,
            amount=30000,
            service_date=date(2024, 1, 1),
            category_guess="pharmacy",
            catalog_id=None,
            canonical_name=None,
            category="pharmacy",
            match_method="unmatched",
        ),
        MatchedLine(
            line_no=7,
            raw_text="INVESTIGATIONS",
            qty=1,
            unit_price=10000,
            amount=10000,
            service_date=date(2024, 1, 2),
            category_guess="investigation",
            catalog_id=None,
            canonical_name=None,
            category="investigation",
            match_method="unmatched",
        ),
    ]
    evidence = [
        Evidence(
            id="E1",
            type="clause",
            text="Room rent shall not exceed ₹5,000 per day for a normal/general room.",
            meta={"page": 7, "similarity": 0.91},
        ),
        Evidence(id="E2", type="calc", text="ratio = 5000/8000 = 0.625", meta={}),
        Evidence(
            id="E3",
            type="catalog",
            text="SURGICAL GLOVES — non-payable consumable. ref_source=DEMO_REFERENCE",
            meta={},
        ),
        Evidence(
            id="E4",
            type="line",
            text="NURSING CHARGES bundled in room rent per catalogue",
            meta={},
        ),
        Evidence(
            id="E5",
            type="kb",
            text="Nursing charges are commonly bundled in room rent per standard policy wording.",
            meta={},
        ),
        Evidence(
            id="E6",
            type="clause",
            text="Where room rent exceeds the eligible limit, all associated charges shall be deducted in proportion.",
            meta={"page": 7, "similarity": 0.88},
        ),
        Evidence(
            id="E7",
            type="calc",
            text="room-linked deduction = 80000 * (1 - 0.625) = 30000",
            meta={},
        ),
        Evidence(
            id="E8",
            type="catalog",
            text="PANTOPRAZOLE INJECTION 40MG — ref_price_high=150. ref_source=DEMO_REFERENCE",
            meta={},
        ),
    ]
    findings = [
        Finding(
            id="F1",
            rule_code="C1",
            kind="coverage",
            severity="red",
            origin="rule",
            line_ids=[1],
            title="Room rent exceeds policy cap",
            explanation=(
                "Actual rent ₹8,000/day exceeds the policy cap of ₹5,000/day. "
                "Proportionate deduction applies to room-linked charges."
            ),
            amount_at_stake=30000,
            confidence="high",
            evidence_ids=["E1", "E2", "E6", "E7"],
        ),
        Finding(
            id="F2",
            rule_code="R3",
            kind="coverage",
            severity="red",
            origin="rule",
            line_ids=[5],
            title="Non-payable consumable",
            explanation=(
                "Surgical gloves are commonly listed as non-payable consumables in standard "
                "insurer exclusion lists. Worth asking about before paying."
            ),
            amount_at_stake=500,
            confidence="high",
            evidence_ids=["E3"],
        ),
        Finding(
            id="F3",
            rule_code="R4",
            kind="billing",
            severity="amber",
            origin="rule",
            line_ids=[2],
            title="Nursing charges possibly bundled",
            explanation=(
                "Nursing charges may already be included in the room rent cap depending on "
                "policy wording. Worth asking about."
            ),
            amount_at_stake=4000,
            confidence="medium",
            evidence_ids=["E4", "E5"],
            uncertain=True,
            agent_note=(
                "KB confirms nursing charges are commonly bundled; "
                "recommend asking at discharge desk."
            ),
        ),
        Finding(
            id="F4",
            rule_code="R5",
            kind="billing",
            severity="amber",
            origin="rule",
            line_ids=[4],
            title="Medication price above reference range",
            explanation=(
                "INJ PANTOP 40MG priced at ₹120/unit; reference benchmark is ₹80-₹150/unit "
                "(DEMO_REFERENCE — a reference benchmark, not a legal cap)."
            ),
            amount_at_stake=None,
            confidence="medium",
            evidence_ids=["E8"],
        ),
        Finding(
            id="F5",
            rule_code="A1",
            kind="billing",
            severity="info",
            origin="agent",
            line_ids=[6],
            title="Pharmacy bulk charge — request itemisation",
            explanation=(
                "The pharmacy charge is billed as a single line without itemisation. "
                "Itemised pharmacy bills are required for insurance claims."
            ),
            amount_at_stake=None,
            confidence="low",
            evidence_ids=["E5"],
            suggested_question=(
                "Please provide an itemised pharmacy bill with individual medicine names, "
                "quantities, and prices."
            ),
        ),
    ]
    simulator = SimulatorResult(
        applied=True,
        billed_total=125100,
        non_payable_total=500,
        room_rent_deduction=30000,
        copay_amount=9460,
        insurer_pays=85140,
        patient_pays=39960,
        steps=[
            WaterfallStep(
                key="billed",
                label="Total Billed",
                amount=125100,
                running_total=125100,
                explanation="Sum of all line items on the bill.",
                evidence_ids=[],
            ),
            WaterfallStep(
                key="non_payable",
                label="Non-payable Items",
                amount=-500,
                running_total=124600,
                explanation="Surgical gloves are listed as non-payable consumables.",
                evidence_ids=["E3"],
            ),
            WaterfallStep(
                key="room_rent",
                label="Room Rent Deduction",
                amount=-30000,
                running_total=94600,
                explanation=(
                    "Proportionate deduction applied (ratio 0.625) to room-linked "
                    "charges totalling ₹80,000."
                ),
                evidence_ids=["E1", "E2", "E6", "E7"],
            ),
            WaterfallStep(
                key="copay",
                label="Co-payment (10%)",
                amount=-9460,
                running_total=85140,
                explanation="10% co-pay applied to admissible amount of ₹94,600.",
                evidence_ids=["E1"],
            ),
            WaterfallStep(
                key="insurer_pays",
                label="Insurer Likely Pays",
                amount=85140,
                running_total=85140,
                explanation=(
                    "Amount the insurer is likely to pay after deductions and co-pay."
                ),
                evidence_ids=[],
            ),
            WaterfallStep(
                key="patient_pays",
                label="You Pay",
                amount=39960,
                running_total=39960,
                explanation="Billed total minus insurer payment.",
                evidence_ids=[],
            ),
        ],
        assumptions=[
            "Estimate based on the terms you confirmed; actual insurer decisions may differ.",
            "Co-pay applied to the admissible amount after deductions.",
            "Proportionate deduction applied to room-linked categories: room, nursing, professional fees, procedures.",
        ],
    )
    summary = Summary(
        billed_total=125100,
        questionable_total=34000,
        insurer_deductions_total=30500,
        insurer_pays=85140,
        patient_pays=39960,
        counts={"red": 2, "amber": 2, "info": 1},
        agent_stats={
            "tool_calls": 8,
            "evidence_items": 8,
            "llm_calls": 3,
            "duration_ms": 4200,
        },
    )
    action_pack = ActionPack(
        desk_questions=[
            DeskQuestion(
                priority=1,
                question=(
                    "Please confirm whether the room rent charge of ₹8,000/day includes "
                    "nursing and RMO charges, or if these are billed separately."
                ),
                why=(
                    "Policy cap is ₹5,000/day; proportionate deduction may apply to "
                    "linked charges."
                ),
                line_ids=[1, 2],
                amount=30000,
            ),
            DeskQuestion(
                priority=2,
                question=(
                    "Please provide documentation confirming that surgical gloves (₹500) "
                    "were medically necessary and not part of routine surgical preparation."
                ),
                why="Surgical gloves are commonly listed as non-payable consumables.",
                line_ids=[5],
                amount=500,
            ),
            DeskQuestion(
                priority=3,
                question=(
                    "Please provide an itemised pharmacy bill with individual medicine names, "
                    "quantities, and prices for the ₹30,000 pharmacy charge."
                ),
                why="Itemised bills are required for insurance claims processing.",
                line_ids=[6],
                amount=None,
            ),
        ],
        letter=Letter(
            subject="Request for Clarification on Hospital Bill — Admission dated 01-Jan-2024",
            body=(
                "Dear Hospital Billing Department,\n\n"
                "I am writing to request clarification on certain charges in my bill for the above admission.\n\n"
                "1. Room rent (₹8,000/day × 5 days = ₹40,000): My policy covers room rent up to ₹5,000/day. "
                "Please confirm whether nursing charges are included in the room rate or billed separately.\n\n"
                "2. Surgical gloves (₹500): Please confirm medical necessity documentation.\n\n"
                "3. Pharmacy charges (₹30,000): Please provide an itemised pharmacy bill.\n\n"
                "This is a reference audit only. All figures are from the submitted bill.\n\n"
                "Yours sincerely,\nPatient"
            ),
            generated_by="template",
        ),
        checklist=[
            "Original itemised hospital bill (all pages)",
            "Discharge summary signed by treating doctor",
            "All investigation reports with lab letterhead",
            "Itemised pharmacy bills with prescriptions",
            "Pre-authorisation letter (if applicable)",
            "Insurance policy document and ID card copy",
            "Patient ID proof",
        ],
    )
    return RunResult(
        run_id=run_id,
        bill=ExtractedBill(
            hospital_name="Apollo Demo Hospital",
            bill_date=date(2024, 1, 5),
            stated_total=125100,
            estimate_amount=120000,
            lines=[
                BillLine(
                    line_no=ln.line_no,
                    raw_text=ln.raw_text,
                    qty=ln.qty,
                    unit_price=ln.unit_price,
                    amount=ln.amount,
                    service_date=ln.service_date,
                    category_guess=ln.category_guess,
                )
                for ln in lines
            ],
        ),
        lines=lines,
        policy_terms={
            "sum_insured": PolicyTerm(
                key="sum_insured",
                status="extracted",
                value=500000,
                quote="Sum Insured: ₹5,00,000",
                page=2,
                similarity=0.92,
            ),
            "room_rent_cap": PolicyTerm(
                key="room_rent_cap",
                status="extracted",
                value=5000,
                room_cap_kind="absolute",
                quote="Room rent shall not exceed ₹5,000 per day for a normal/general room.",
                page=7,
                similarity=0.91,
            ),
            "copay_pct": PolicyTerm(
                key="copay_pct",
                status="extracted",
                value=10,
                quote="The insured shall bear 10% of the admissible claim amount as co-payment.",
                page=8,
                similarity=0.89,
            ),
            "proportionate_deduction": PolicyTerm(
                key="proportionate_deduction",
                status="extracted",
                value=True,
                quote="Where room rent exceeds the eligible limit, all associated charges shall be deducted in proportion.",
                page=7,
                similarity=0.88,
            ),
        },
        policy=ResolvedPolicy(
            is_insured=True,
            sum_insured=500000,
            room_rent_cap_per_day=5000,
            copay_pct=10,
            proportionate_deduction=True,
            term_evidence={
                "sum_insured": "E1",
                "room_rent_cap": "E1",
                "copay_pct": "E1",
                "proportionate_deduction": "E6",
            },
        ),
        findings=findings,
        evidence=evidence,
        simulator=simulator,
        summary=summary,
        action_pack=action_pack,
        mode="live",
    )


@router.post("/runs", response_model=RunCreateResponse)
async def create_run(body: RunCreateRequest) -> RunCreateResponse:
    return RunCreateResponse(run_id=str(uuid.uuid4()))


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str) -> RunStatusResponse:
    return RunStatusResponse(status="done", phase="complete")


@router.put("/runs/{run_id}/confirm")
async def confirm_run(run_id: str, body: RunConfirmRequest) -> Response:
    return Response(status_code=202)


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> dict:
    return {"message": "SSE not yet implemented in Phase 1"}


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, since: int = 0) -> list[TraceEvent]:
    return []


@router.get("/runs/{run_id}/result", response_model=RunResult)
async def get_run_result(run_id: str) -> RunResult:
    return _example_run_result(run_id)
