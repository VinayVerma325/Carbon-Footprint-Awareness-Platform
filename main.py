import datetime
import logging
import os
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import Config
from core.calculator import CarbonCalculator, RecommendationEngine
from services.google_services import RoutesServiceClient, FirestoreRepository
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Setup logging
logger = logging.getLogger("CarbonPlatformServer")

app = FastAPI(
    title="CarbonWise Platform API",
    description="Backend API serving the Carbon Footprint Awareness Platform.",
    version="1.0.0"
)

# Configure CORS
# allow_credentials=False because no cookies/auth headers are used anywhere in
# this API (user_id is just a plain request field). Wildcard origin + credentials=True
# is an unnecessary, meaningless-for-this-app combination that browsers also reject
# unless the server echoes back a specific origin instead of "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Initialize services
routes_client = RoutesServiceClient()
db_repo = FirestoreRepository()


# Request/Response Models
class RouteRequest(BaseModel):
    origin: str = Field(..., min_length=1, description="Starting location address")
    destination: str = Field(..., min_length=1, description="Ending location address")
    travel_mode: str = Field("car", description="Travel mode (car, bus, train, walk, bike)")


class TransportLog(BaseModel):
    distance: float = Field(..., ge=0)
    mode: str
    vehicle_type: Optional[str] = None


class CarbonCalculationRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    electricity_kwh: float = Field(0.0, ge=0)
    gas_m3: float = Field(0.0, ge=0)
    transport: List[TransportLog] = Field(default_factory=list)
    diet_type: str = Field("average")
    diet_days: int = Field(1, ge=1)
    waste_kg: float = Field(0.0, ge=0)
    waste_recycling_rate: float = Field(0.0, ge=0.0, le=1.0)


class DailyActionRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    action: str = Field(...)
    title: str = Field(...)
    carbon_offset_kg: float = Field(..., ge=0)


# Serve Frontend
@app.get("/")
def read_root() -> FileResponse:
    """Serve the primary dashboard interface."""
    return FileResponse(
        os.path.join(BASE_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/style.css")
@app.get("/app.css")
def read_css() -> FileResponse:
    """Serve dashboard styling stylesheet with caching enabled for efficiency."""
    return FileResponse(
        os.path.join(BASE_DIR, "style.css"),
        headers={"Cache-Control": "public, max-age=31536000"}  # cache for 1 year
    )


@app.get("/app.js")
def read_js() -> FileResponse:
    """Serve dashboard client script with caching enabled for efficiency."""
    return FileResponse(
        os.path.join(BASE_DIR, "app.js"),
        headers={"Cache-Control": "public, max-age=31536000"}  # cache for 1 year
    )


# API Endpoints
@app.post("/api/route")
def estimate_route_distance(payload: RouteRequest) -> Dict[str, Any]:
    """Estimate distance and duration between origin and destination using Google Routes API."""
    try:
        result = routes_client.calculate_route(
            origin=payload.origin,
            destination=payload.destination,
            travel_mode=payload.travel_mode
        )
        return result
    except ValueError as val_err:
        logger.warning(f"Validation error in route parameters: {str(val_err)}")
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as e:
        logger.error(f"Unexpected error in routing api: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error calculating route.")


@app.post("/api/calculate")
def calculate_and_save_footprint(payload: CarbonCalculationRequest) -> Dict[str, Any]:
    """Calculate carbon footprint from user metrics and save log to the database."""
    try:
        # Convert Pydantic request to dictionary for calculation engine
        inputs = payload.model_dump()
        calculations = CarbonCalculator.calculate_total(inputs)
        
        # Prepare log entry
        log_entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "electricity_co2": calculations["electricity_co2"],
            "gas_co2": calculations["gas_co2"],
            "transport_co2": calculations["transport_co2"],
            "diet_co2": calculations["diet_co2"],
            "waste_co2": calculations["waste_co2"],
            "total_co2": calculations["total_co2"],
            "inputs": {
                "electricity_kwh": payload.electricity_kwh,
                "gas_m3": payload.gas_m3,
                "transport": [t.model_dump() for t in payload.transport],
                "diet_type": payload.diet_type,
                "waste_kg": payload.waste_kg,
                "waste_recycling_rate": payload.waste_recycling_rate
            }
        }
        
        # Save to database
        saved = db_repo.save_user_log(payload.user_id, log_entry)
        if not saved:
            logger.error("Failed to commit user log to repository.")
            
        return {
            "status": "success",
            "calculations": calculations
        }
        
    except ValueError as val_err:
        logger.warning(f"Carbon calculation input value error: {str(val_err)}")
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as e:
        logger.error(f"Unexpected error in carbon calculation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error computing carbon footprint.")


@app.post("/api/action")
def log_green_action(payload: DailyActionRequest) -> Dict[str, Any]:
    """Log an offset/green action completed by the user."""
    try:
        action_data = {
            "action": payload.action,
            "title": payload.title,
            "carbon_offset_kg": payload.carbon_offset_kg,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        saved = db_repo.save_daily_action(payload.user_id, action_data)
        if not saved:
            raise HTTPException(status_code=500, detail="Failed to save green action log.")
            
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error logging daily action: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal database error.")


@app.get("/api/action")
def get_green_actions(user_id: str = Query(..., min_length=1)) -> List[Dict[str, Any]]:
    """Retrieve history of green actions for a user."""
    try:
        actions = db_repo.get_daily_actions(user_id)
        return actions
    except Exception as e:
        logger.error(f"Error fetching user actions: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal database retrieval error.")


@app.get("/api/logs")
def get_calculation_history(user_id: str = Query(..., min_length=1)) -> List[Dict[str, Any]]:
    """Retrieve history of calculation logs for a user."""
    try:
        logs = db_repo.get_user_logs(user_id)
        return logs
    except Exception as e:
        logger.error(f"Error fetching user logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal database retrieval error.")


@app.delete("/api/logs")
def clear_calculation_history(user_id: str = Query(..., min_length=1)) -> Dict[str, Any]:
    """Clear all calculation logs and actions for a user."""
    try:
        cleared_logs = db_repo.clear_user_logs(user_id)
        cleared_actions = db_repo.clear_user_actions(user_id)
        if not cleared_logs or not cleared_actions:
            raise HTTPException(status_code=500, detail="Failed to clear user logs/actions.")
        return {"status": "success", "message": "All calculation history and actions cleared."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing user data: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal database error.")


@app.get("/api/recommendations")
def get_personalized_recommendations(user_id: str = Query(..., min_length=1)) -> List[Dict[str, Any]]:
    """Analyze database logs to generate structured, personalized insights for the user."""
    try:
        logs = db_repo.get_user_logs(user_id)
        profile = db_repo.get_user_profile(user_id)
        
        # If no logs yet, calculate recommendations based on default profile
        if not logs:
            default_inputs = {
                "electricity_kwh": 5.0,
                "gas_m3": 0.0,
                "transport": [{"distance": 10.0, "mode": "car", "vehicle_type": "petrol"}],
                "diet_type": "average",
                "waste_kg": 1.5,
                "waste_recycling_rate": 0.3
            }
            recs = RecommendationEngine.analyze_and_recommend(default_inputs, [])
        else:
            recs = RecommendationEngine.analyze_and_recommend(profile, logs)
            
        return recs
    except Exception as e:
        logger.error(f"Error generating recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal processing error.")


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting CarbonWise FastAPI backend at http://{Config.HOST}:{Config.PORT}")
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
