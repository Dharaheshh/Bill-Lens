from fastapi import APIRouter

from app.schemas import SampleInfo

router = APIRouter()

SAMPLES: list[SampleInfo] = [
    SampleInfo(
        id="sample-a-ortho-insured",
        kind="bill",
        title="Orthopaedic Surgery (Insured)",
        description="46-line bill with room rent, consumables, duplicate charges, and inflation. Policy A applies.",
        thumb_url="/static/samples/sample-a-thumb.png",
        insured=True,
    ),
    SampleInfo(
        id="sample-b-pctsi-insured",
        kind="bill",
        title="General Surgery (% of SI cap)",
        description="35-line bill showcasing percentage-of-sum-insured room cap and flat-cap deduction.",
        thumb_url="/static/samples/sample-b-thumb.png",
        insured=True,
    ),
    SampleInfo(
        id="sample-c-uninsured-photo",
        kind="bill",
        title="Pharmacy Bill (Uninsured, phone photo)",
        description="30-line pharmacy-heavy bill captured as a phone photo. No insurance applied.",
        thumb_url="/static/samples/sample-c-thumb.png",
        insured=False,
    ),
    SampleInfo(
        id="policy-a-flat-cap",
        kind="policy",
        title="Demo Health Assure — Plan A (Flat Cap)",
        description="Room rent capped at ₹5,000/day, 10% co-pay, proportionate deduction, SI ₹5,00,000.",
        thumb_url=None,
        insured=None,
    ),
    SampleInfo(
        id="policy-b-pct-si",
        kind="policy",
        title="Demo Health Assure — Plan B (% SI Cap)",
        description="Room rent capped at 1% of sum insured per day, 20% co-pay, SI ₹5,00,000.",
        thumb_url=None,
        insured=None,
    ),
]


@router.get("/samples", response_model=list[SampleInfo])
async def list_samples() -> list[SampleInfo]:
    return SAMPLES
