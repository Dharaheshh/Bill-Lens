import uuid

from fastapi import APIRouter

from app.schemas import RunCreateResponse

router = APIRouter()


@router.post("/demo/{sample_id}", response_model=RunCreateResponse)
async def start_demo(sample_id: str) -> RunCreateResponse:
    return RunCreateResponse(run_id=str(uuid.uuid4()))
