"""Avalanche-risk API."""

from fastapi import APIRouter

from app.ml.avalanche_inference import predict_location
from app.models import AvalancheRiskPrediction, RiskPredictionRequest

router = APIRouter(prefix="/api/v1", tags=["avalanche-risk"])


@router.post("/avalanche-risk", response_model=AvalancheRiskPrediction)
def avalanche_risk(request: RiskPredictionRequest) -> AvalancheRiskPrediction:
    """Estimate calibrated avalanche occurrence risk in the next 24 hours at a 1 km cell."""
    return AvalancheRiskPrediction.model_validate(
        predict_location(request.latitude, request.longitude, request.timestamp).to_dict()
    )
