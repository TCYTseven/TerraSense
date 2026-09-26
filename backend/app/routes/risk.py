"""Cell-level production risk endpoint."""

from fastapi import APIRouter

from app.ml.risk_inference import predict_location
from app.models import LandslideRiskPrediction, RiskPredictionRequest

router = APIRouter(prefix="/api/v1", tags=["landslide-risk"])


@router.post("/landslide-risk", response_model=LandslideRiskPrediction)
def landslide_risk(request: RiskPredictionRequest) -> LandslideRiskPrediction:
    """Estimate calibrated next-week rainfall-triggered landslide risk at a 1 km cell."""
    return LandslideRiskPrediction.model_validate(
        predict_location(request.latitude, request.longitude, request.timestamp).to_dict()
    )
