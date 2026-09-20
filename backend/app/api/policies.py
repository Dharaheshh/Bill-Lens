import uuid

from fastapi import APIRouter

from app.schemas import (
    PolicyConfirmRequest,
    PolicyCreateResponse,
    PolicyGetResponse,
    PolicyTerm,
    ResolvedPolicy,
)

router = APIRouter()

_EXAMPLE_TERMS: dict[str, PolicyTerm] = {
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
}


@router.post("/policies", response_model=PolicyCreateResponse)
async def create_policy() -> PolicyCreateResponse:
    return PolicyCreateResponse(policy_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()))


@router.get("/policies/{policy_id}", response_model=PolicyGetResponse)
async def get_policy(policy_id: str) -> PolicyGetResponse:
    return PolicyGetResponse(
        policy_id=policy_id,
        terms=_EXAMPLE_TERMS,
        confirmed=False,
        status="done",
    )


@router.put("/policies/{policy_id}/terms", response_model=ResolvedPolicy)
async def confirm_policy_terms(policy_id: str, body: PolicyConfirmRequest) -> ResolvedPolicy:
    terms = body.terms
    si = terms.get("sum_insured")
    room = terms.get("room_rent_cap")
    copay = terms.get("copay_pct")
    prop = terms.get("proportionate_deduction")
    room_cap: float | None = None
    if room and room.value is not None:
        if room.room_cap_kind == "pct_si" and si and si.value:
            room_cap = round(float(si.value) * float(room.value) / 100, 2)
        else:
            room_cap = float(room.value)
    return ResolvedPolicy(
        is_insured=True,
        sum_insured=float(si.value) if si and si.value is not None else None,
        room_rent_cap_per_day=room_cap,
        copay_pct=float(copay.value) if copay and copay.value is not None else 0.0,
        proportionate_deduction=bool(prop.value) if prop and prop.value is not None else False,
        term_evidence={k: f"E{i + 1}" for i, k in enumerate(terms.keys())},
    )
