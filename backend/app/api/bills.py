import uuid

from fastapi import APIRouter

from app.schemas import BillCreateResponse

router = APIRouter()


@router.post("/bills", response_model=BillCreateResponse)
async def create_bill() -> BillCreateResponse:
    return BillCreateResponse(bill_id=str(uuid.uuid4()))
