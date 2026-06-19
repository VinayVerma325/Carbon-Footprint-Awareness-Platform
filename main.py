"""
CarbonWise Platform — FastAPI application server.

Serves the single-page frontend (``index.html``, ``style.css``, ``app.js``)
and exposes a RESTful JSON API for carbon footprint calculation, green-action
logging, calculation history retrieval, and personalized recommendation
generation.

Security controls implemented at this layer:
    • Content-Security-Policy (CSP) restricting script/style/font sources.
    • Clickjacking prevention via ``X-Frame-Options: DENY``.
    • MIME-sniffing prevention via ``X-Content-Type-Options: nosniff``.
    • Referrer leak prevention via ``Referrer-Policy``.
    • Permissions-Policy restricting browser feature access.
    • HSTS header for transport security enforcement.
    • CORS restricted to ``Config.ALLOWED_ORIGINS``.
    • GZip compression for payloads > 1 KB.
    • Pydantic-enforced input validation with strict field constraints.
    • Structured JSON error responses via global exception handler.
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from config import Config
from core.calculator import CarbonCalculator, RecommendationEngine
from exceptions import CarbonWiseError, ValidationError
from services.google_services import FirestoreRepository, RoutesServiceClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("CarbonPlatformServer")

# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="CarbonWise Platform API",
    description=(
        "Backend API serving the Carbon Footprint Awareness Platform. "
        "Provides endpoints for carbon calculation, action logging, "
        "history retrieval, and personalized recommendations."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Middleware Stack
# ---------------------------------------------------------------------------

# CORS — restrict to known origins only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# Response compression for payloads > 1 KB.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    """Inject robust security HTTP headers on every API response.

    Headers applied:
        • Content-Security-Policy (CSP)
        • X-Frame-Options
        • X-Content-Type-Options
        • X-XSS-Protection (legacy)
        • Referrer-Policy
        • Permissions-Policy
        • Strict-Transport-Security (HSTS)
        • Cache-Control for API responses
    """
    response = await call_next(request)
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains; preload"
    )
    return response


# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------


@app.exception_handler(CarbonWiseError)
async def carbonwise_error_handler(
    request: Request, exc: CarbonWiseError
) -> JSONResponse:
    """Return structured JSON error responses for all domain exceptions."""
    logger.warning(
        "Domain error [%s]: %s (HTTP %d)",
        exc.error_code,
        exc.message,
        exc.http_status,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": exc.error_code,
            "detail": exc.message,
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Catch stray ValueErrors and return 400 with a structured body."""
    logger.warning("ValueError: %s", str(exc))
    return JSONResponse(
        status_code=400,
        content={
            "error": "VALIDATION_ERROR",
            "detail": str(exc),
        },
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Service Initialization
# ---------------------------------------------------------------------------
routes_client = RoutesServiceClient()
db_repo = FirestoreRepository()


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------


class RouteRequest(BaseModel):
    """Schema for the ``POST /api/route`` endpoint."""

    origin: str = Field(
        ..., min_length=1, max_length=500,
        description="Starting location address or coordinates.",
    )
    destination: str = Field(
        ..., min_length=1, max_length=500,
        description="Ending location address or coordinates.",
    )
    travel_mode: str = Field(
        "car", max_length=50,
        description="Travel mode (car, bus, train, walk, bike, flight).",
    )


class TransportLog(BaseModel):
    """A single transport leg within a carbon calculation request."""

    distance: float = Field(..., ge=0, le=100_000.0)
    mode: str = Field(..., max_length=50)
    vehicle_type: str | None = Field(None, max_length=50)


class CarbonCalculationRequest(BaseModel):
    """Schema for the ``POST /api/calculate`` endpoint."""

    user_id: str = Field(..., min_length=1, max_length=100)
    electricity_kwh: float = Field(0.0, ge=0, le=100_000.0)
    gas_m3: float = Field(0.0, ge=0, le=100_000.0)
    transport: List[TransportLog] = Field(default_factory=list)
    diet_type: str = Field("average", max_length=50)
    diet_days: int = Field(1, ge=1, le=365)
    waste_kg: float = Field(0.0, ge=0, le=100_000.0)
    waste_recycling_rate: float = Field(0.0, ge=0.0, le=1.0)


class DailyActionRequest(BaseModel):
    """Schema for the ``POST /api/action`` endpoint."""

    user_id: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=150)
    carbon_offset_kg: float = Field(..., ge=0, le=100_000.0)


# ---------------------------------------------------------------------------
# Static Asset Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def read_root() -> FileResponse:
    """Serve the primary dashboard interface."""
    return FileResponse(
        os.path.join(BASE_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/style.css")
@app.get("/app.css")
def read_css() -> FileResponse:
    """Serve the dashboard stylesheet with long-term caching."""
    return FileResponse(
        os.path.join(BASE_DIR, "style.css"),
        headers={"Cache-Control": "public, max-age=31536000"},
    )


@app.get("/app.js")
def read_js() -> FileResponse:
    """Serve the dashboard client script with long-term caching."""
    return FileResponse(
        os.path.join(BASE_DIR, "app.js"),
        headers={"Cache-Control": "public, max-age=31536000"},
    )


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    """Return platform health status and configuration summary.

    Useful for uptime monitors, CI/CD pipelines, and deployment validation.
    """
    return {
        "status": "healthy",
        "version": "1.0.0",
        "environment": Config.ENV,
        "services": {
            "google_routes": "configured" if Config.GOOGLE_MAPS_API_KEY else "simulated_fallback",
            "firestore": "local_fallback" if db_repo.use_fallback else "live",
        },
    }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/route")
def estimate_route_distance(payload: RouteRequest) -> Dict[str, Any]:
    """Estimate distance and duration between origin and destination.

    Delegates to the Google Routes API v2 when a valid API key is
    configured; otherwise returns a deterministic simulated fallback.
    """
    try:
        result = routes_client.calculate_route(
            origin=payload.origin,
            destination=payload.destination,
            travel_mode=payload.travel_mode,
        )
        return result
    except ValidationError:
        raise
    except ValueError as val_err:
        logger.warning("Validation error in route parameters: %s", str(val_err))
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.error("Unexpected error in routing API: %s", str(exc))
        raise HTTPException(
            status_code=500,
            detail="Internal server error calculating route.",
        )


@app.post("/api/calculate")
def calculate_and_save_footprint(
    payload: CarbonCalculationRequest,
) -> Dict[str, Any]:
    """Calculate carbon footprint from user metrics and persist to the database.

    Automatically deducts today's logged green-action offsets to compute
    the ``net_co2`` value returned in the response.
    """
    try:
        inputs = payload.model_dump()
        calculations = CarbonCalculator.calculate_total(inputs)

        # Compute daily offset for today (UTC)
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        actions = db_repo.get_daily_actions(payload.user_id)
        daily_offset_kg = sum(
            float(act.get("carbon_offset_kg", 0.0))
            for act in actions
            if act.get("timestamp", "").startswith(today_str)
        )

        net_co2 = CarbonCalculator.calculate_net(
            calculations["total_co2"], daily_offset_kg
        )
        calculations["net_co2"] = net_co2

        # Prepare log entry
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "electricity_co2": calculations["electricity_co2"],
            "gas_co2": calculations["gas_co2"],
            "transport_co2": calculations["transport_co2"],
            "diet_co2": calculations["diet_co2"],
            "waste_co2": calculations["waste_co2"],
            "total_co2": calculations["total_co2"],
            "net_co2": calculations["net_co2"],
            "inputs": {
                "electricity_kwh": payload.electricity_kwh,
                "gas_m3": payload.gas_m3,
                "transport": [t.model_dump() for t in payload.transport],
                "diet_type": payload.diet_type,
                "waste_kg": payload.waste_kg,
                "waste_recycling_rate": payload.waste_recycling_rate,
            },
        }

        saved = db_repo.save_user_log(payload.user_id, log_entry)
        if not saved:
            logger.error("Failed to commit user log to repository.")

        return {"status": "success", "calculations": calculations}

    except (ValidationError, CarbonWiseError):
        raise
    except ValueError as val_err:
        logger.warning("Carbon calculation input value error: %s", str(val_err))
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.error("Unexpected error in carbon calculation: %s", str(exc))
        raise HTTPException(
            status_code=500,
            detail="Internal server error computing carbon footprint.",
        )


@app.post("/api/action")
def log_green_action(payload: DailyActionRequest) -> Dict[str, Any]:
    """Log an offset / green action completed by the user."""
    try:
        action_data: Dict[str, Any] = {
            "action": payload.action,
            "title": payload.title,
            "carbon_offset_kg": payload.carbon_offset_kg,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        saved = db_repo.save_daily_action(payload.user_id, action_data)
        if not saved:
            raise HTTPException(
                status_code=500, detail="Failed to save green action log."
            )

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error logging daily action: %s", str(exc))
        raise HTTPException(status_code=500, detail="Internal database error.")


@app.get("/api/action")
def get_green_actions(
    user_id: str = Query(..., min_length=1),
) -> List[Dict[str, Any]]:
    """Retrieve history of green actions for a given user."""
    try:
        return db_repo.get_daily_actions(user_id)
    except Exception as exc:
        logger.error("Error fetching user actions: %s", str(exc))
        raise HTTPException(
            status_code=500, detail="Internal database retrieval error."
        )


@app.get("/api/logs")
def get_calculation_history(
    user_id: str = Query(..., min_length=1),
) -> List[Dict[str, Any]]:
    """Retrieve calculation logs, dynamically injecting ``net_co2`` from daily offsets."""
    try:
        logs = db_repo.get_user_logs(user_id)
        actions = db_repo.get_daily_actions(user_id)

        # Group offsets by calendar day (YYYY-MM-DD)
        offsets_by_day: Dict[str, float] = {}
        for act in actions:
            ts = act.get("timestamp", "")
            if ts:
                day = ts[:10]
                offsets_by_day[day] = offsets_by_day.get(day, 0.0) + float(
                    act.get("carbon_offset_kg", 0.0)
                )

        # Inject net_co2 dynamically into each log entry
        for log in logs:
            total_co2 = float(log.get("total_co2", 0.0))
            ts = log.get("timestamp", "")
            day = ts[:10] if ts else ""
            offset_kg = offsets_by_day.get(day, 0.0)
            log["net_co2"] = CarbonCalculator.calculate_net(total_co2, offset_kg)

        return logs
    except Exception as exc:
        logger.error("Error fetching user logs: %s", str(exc))
        raise HTTPException(
            status_code=500, detail="Internal database retrieval error."
        )


@app.delete("/api/logs")
def clear_calculation_history(
    user_id: str = Query(..., min_length=1),
) -> Dict[str, Any]:
    """Clear all calculation logs and green actions for a user."""
    try:
        cleared_logs = db_repo.clear_user_logs(user_id)
        cleared_actions = db_repo.clear_user_actions(user_id)
        if not cleared_logs or not cleared_actions:
            raise HTTPException(
                status_code=500, detail="Failed to clear user logs/actions."
            )
        return {
            "status": "success",
            "message": "All calculation history and actions cleared.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error clearing user data: %s", str(exc))
        raise HTTPException(status_code=500, detail="Internal database error.")


@app.get("/api/recommendations")
def get_personalized_recommendations(
    user_id: str = Query(..., min_length=1),
) -> List[Dict[str, Any]]:
    """Analyze historical logs to generate prioritized recommendations."""
    try:
        logs = db_repo.get_user_logs(user_id)
        profile = db_repo.get_user_profile(user_id)

        if not logs:
            # Use sensible defaults for first-time users
            default_inputs: Dict[str, Any] = {
                "electricity_kwh": 5.0,
                "gas_m3": 0.0,
                "transport": [
                    {"distance": 10.0, "mode": "car", "vehicle_type": "petrol"}
                ],
                "diet_type": "average",
                "waste_kg": 1.5,
                "waste_recycling_rate": 0.3,
            }
            return RecommendationEngine.analyze_and_recommend(default_inputs, [])

        return RecommendationEngine.analyze_and_recommend(profile, logs)
    except Exception as exc:
        logger.error("Error generating recommendations: %s", str(exc))
        raise HTTPException(
            status_code=500, detail="Internal processing error."
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info(
        "Starting CarbonWise FastAPI backend at http://%s:%s",
        Config.HOST,
        Config.PORT,
    )
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
