from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", version="0.1.0")


@router.get("/ready", response_model=HealthResponse)
async def readiness_check():
    # M2: add DB + Redis ping here
    return HealthResponse(status="ok", version="0.1.0")
