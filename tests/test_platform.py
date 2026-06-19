"""
Comprehensive test suite for the CarbonWise platform.

Covers:
    • Unit tests for all ``CarbonCalculator`` conversion methods.
    • Unit tests for ``RecommendationEngine`` pattern analysis.
    • Mock-based tests for ``RoutesServiceClient`` (API + fallback).
    • Local-fallback CRUD tests for ``FirestoreRepository``.
    • Integration tests for every FastAPI endpoint (including ``/api/health``).
    • Security header verification (CSP, HSTS, Permissions-Policy, etc.).
    • Input validation edge-case coverage.
    • Custom exception hierarchy tests.
    • Input sanitization utility tests.

Run with::

    python -m pytest tests/test_platform.py -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from config import Config
from core.calculator import CarbonCalculator, RecommendationEngine
from exceptions import (
    CarbonWiseError,
    CalculationError,
    DatabaseError,
    ExternalServiceError,
    ResourceNotFoundError,
    ValidationError,
)
from fastapi.testclient import TestClient
from main import app
from sanitizer import (
    clamp_float,
    normalize_diet_type,
    normalize_travel_mode,
    sanitize_text,
    sanitize_user_id,
)
from services.google_services import FirestoreRepository, RoutesServiceClient


# ===================================================================
# Unit Tests — CarbonCalculator
# ===================================================================


class TestCarbonCalculator(unittest.TestCase):
    """Granular unit tests for the carbon footprint conversion engines."""

    def test_electricity_calculations(self) -> None:
        """Verify electricity CO₂ formula: kWh × 0.385."""
        self.assertEqual(CarbonCalculator.calculate_electricity(100.0), 38.5)
        self.assertEqual(CarbonCalculator.calculate_electricity(0.0), 0.0)

        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_electricity(-10.0)

    def test_gas_calculations(self) -> None:
        """Verify gas CO₂ formula: m³ × 2.03."""
        self.assertEqual(CarbonCalculator.calculate_gas(50.0), 101.5)
        self.assertEqual(CarbonCalculator.calculate_gas(0.0), 0.0)

        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_gas(-5.0)

    def test_transport_calculations(self) -> None:
        """Verify transport CO₂ factors for all supported modes."""
        # Car — petrol: 10 miles × 0.404 = 4.04 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(10.0, "car", "petrol"), 4.04
        )

        # Car — electric: 10 miles × 0.050 = 0.50 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(10.0, "car", "electric"), 0.50
        )

        # Bus: 20 miles × 0.100 = 2.00 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(20.0, "bus"), 2.00
        )

        # Train: 50 miles × 0.050 = 2.50 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(50.0, "train"), 2.50
        )

        # Flight short (<300 miles): 200 miles × 0.250 = 50.00 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(200.0, "flight"), 50.00
        )

        # Flight long (>=300 miles): 500 miles × 0.150 = 75.00 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(500.0, "flight"), 75.00
        )

        # Bicycle: 10 miles × 0.0 = 0.0 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(10.0, "bicycle"), 0.0
        )

        # Walk: 5 miles × 0.0 = 0.0 kg CO₂
        self.assertEqual(
            CarbonCalculator.calculate_transport(5.0, "walk"), 0.0
        )

        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_transport(-20.0, "car")

    def test_diet_calculations(self) -> None:
        """Verify diet CO₂ factors across all profiles."""
        self.assertEqual(CarbonCalculator.calculate_diet(7, "vegan"), 28.7)
        self.assertEqual(
            CarbonCalculator.calculate_diet(3, "heavy_meat"), 27.0
        )
        # Invalid key falls back to average: 1 day × 6.8 = 6.8
        self.assertEqual(
            CarbonCalculator.calculate_diet(1, "invalid_diet"), 6.8
        )

        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_diet(-1, "vegan")

    def test_waste_calculations(self) -> None:
        """Verify waste CO₂ formula with recycling rate partitioning."""
        # 10 kg waste, 30% recycled: (7 × 0.500) + (3 × 0.050) = 3.65
        self.assertEqual(CarbonCalculator.calculate_waste(10.0, 0.3), 3.65)
        self.assertEqual(CarbonCalculator.calculate_waste(10.0, 1.0), 0.50)
        self.assertEqual(CarbonCalculator.calculate_waste(10.0, 0.0), 5.0)

        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_waste(-1.0, 0.5)
        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_waste(10.0, 1.2)

    def test_total_calculation_aggregator(self) -> None:
        """Verify aggregated total across all categories."""
        inputs = {
            "electricity_kwh": 10.0,
            "gas_m3": 2.0,
            "transport": [
                {"distance": 15.0, "mode": "car", "vehicle_type": "hybrid"},
                {"distance": 5.0, "mode": "walk"},
            ],
            "diet_type": "vegetarian",
            "diet_days": 1,
            "waste_kg": 2.0,
            "waste_recycling_rate": 0.5,
        }
        # electricity: 10 × 0.385 = 3.85
        # gas: 2 × 2.03 = 4.06
        # transport 1: 15 × 0.200 = 3.00
        # transport 2: 5 × 0.0 = 0.0
        # diet: 1 × 4.7 = 4.7
        # waste: 2 kg, 0.5 recycling → 0.55
        # total = 16.16
        res = CarbonCalculator.calculate_total(inputs)
        self.assertEqual(res["electricity_co2"], 3.85)
        self.assertEqual(res["gas_co2"], 4.06)
        self.assertEqual(res["diet_co2"], 4.7)
        self.assertEqual(res["waste_co2"], 0.55)
        self.assertEqual(res["total_co2"], 16.16)

    def test_net_co2_calculations(self) -> None:
        """Verify net footprint clamping: total − offset, min 0."""
        self.assertEqual(CarbonCalculator.calculate_net(10.0, 4.0), 6.0)
        self.assertEqual(CarbonCalculator.calculate_net(5.0, 10.0), 0.0)

        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_net(-1.0, 5.0)
        with self.assertRaises((ValueError, ValidationError)):
            CarbonCalculator.calculate_net(5.0, -1.0)

    def test_zero_inputs_total(self) -> None:
        """Verify that all-zero inputs produce zero emissions."""
        inputs = {
            "electricity_kwh": 0,
            "gas_m3": 0,
            "transport": [],
            "diet_type": "vegan",
            "diet_days": 0,
            "waste_kg": 0,
            "waste_recycling_rate": 0,
        }
        res = CarbonCalculator.calculate_total(inputs)
        self.assertEqual(res["total_co2"], 0.0)


# ===================================================================
# Unit Tests — RecommendationEngine
# ===================================================================


class TestRecommendationEngine(unittest.TestCase):
    """Unit tests for the pattern analysis and recommendation generator."""

    def test_recommendation_trends(self) -> None:
        """Verify transport recommendation fires when transport is high."""
        user_data = {
            "electricity_kwh": 2.0,
            "gas_m3": 0.0,
            "transport": [
                {"distance": 50.0, "mode": "car", "vehicle_type": "petrol"}
            ],
            "diet_type": "vegan",
            "waste_kg": 0.2,
            "waste_recycling_rate": 1.0,
        }
        recs = RecommendationEngine.analyze_and_recommend(user_data, [])
        categories = [r["category"] for r in recs]

        self.assertIn("transport", categories)
        self.assertNotIn("diet", categories)

    def test_all_sustainable_default_nudge(self) -> None:
        """Verify green-nudge message when all categories are sustainable."""
        user_data = {
            "electricity_kwh": 2.0,
            "gas_m3": 0.0,
            "transport": [
                {"distance": 2.0, "mode": "car", "vehicle_type": "electric"}
            ],
            "diet_type": "vegan",
            "waste_kg": 0.2,
            "waste_recycling_rate": 0.9,
        }
        recs = RecommendationEngine.analyze_and_recommend(user_data, [])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["category"], "general")
        self.assertEqual(recs[0]["title"], "Maintain Your Green Habits!")

    def test_historical_log_averaging(self) -> None:
        """Verify recommendations use averaged historical data when available."""
        historical = [
            {
                "electricity_co2": 5.0,
                "gas_co2": 0.0,
                "transport_co2": 10.0,
                "diet_co2": 6.8,
                "waste_co2": 0.5,
            },
            {
                "electricity_co2": 3.0,
                "gas_co2": 0.0,
                "transport_co2": 8.0,
                "diet_co2": 6.8,
                "waste_co2": 0.3,
            },
        ]
        recs = RecommendationEngine.analyze_and_recommend({}, historical)
        categories = [r["category"] for r in recs]
        # Average transport = 9.0 > 3.0 target
        self.assertIn("transport", categories)
        # Average electricity = 4.0 > 2.5 target
        self.assertIn("electricity", categories)

    def test_recommendations_sorted_by_savings(self) -> None:
        """Verify recommendations are sorted descending by savings potential."""
        user_data = {
            "electricity_kwh": 50.0,
            "gas_m3": 0.0,
            "transport": [
                {"distance": 100.0, "mode": "car", "vehicle_type": "petrol"}
            ],
            "diet_type": "heavy_meat",
            "waste_kg": 10.0,
            "waste_recycling_rate": 0.0,
        }
        recs = RecommendationEngine.analyze_and_recommend(user_data, [])
        savings = [r["estimated_savings_kg"] for r in recs]
        self.assertEqual(savings, sorted(savings, reverse=True))

    def test_gas_recommendation_fires(self) -> None:
        """Verify gas recommendation triggers when gas usage is high."""
        user_data = {
            "electricity_kwh": 2.0,
            "gas_m3": 5.0,  # 5.0 * 2.03 = 10.15 kg > 1.5 target
            "transport": [
                {"distance": 2.0, "mode": "car", "vehicle_type": "electric"}
            ],
            "diet_type": "vegan",
            "waste_kg": 0.2,
            "waste_recycling_rate": 0.9,
        }
        recs = RecommendationEngine.analyze_and_recommend(user_data, [])
        categories = [r["category"] for r in recs]
        self.assertIn("gas", categories)


# ===================================================================
# Unit Tests — Custom Exceptions
# ===================================================================


class TestCustomExceptions(unittest.TestCase):
    """Verify the custom exception hierarchy and attributes."""

    def test_base_exception_attributes(self) -> None:
        """CarbonWiseError should carry message, error_code, and http_status."""
        exc = CarbonWiseError("test error", error_code="TEST", http_status=418)
        self.assertEqual(exc.message, "test error")
        self.assertEqual(exc.error_code, "TEST")
        self.assertEqual(exc.http_status, 418)
        self.assertEqual(str(exc), "test error")

    def test_validation_error_field(self) -> None:
        """ValidationError should carry an optional field name."""
        exc = ValidationError("bad input", field="electricity_kwh")
        self.assertEqual(exc.http_status, 400)
        self.assertEqual(exc.field, "electricity_kwh")

    def test_calculation_error(self) -> None:
        """CalculationError should default to HTTP 422."""
        exc = CalculationError()
        self.assertEqual(exc.http_status, 422)

    def test_resource_not_found_error(self) -> None:
        """ResourceNotFoundError should default to HTTP 404."""
        exc = ResourceNotFoundError("user not found")
        self.assertEqual(exc.http_status, 404)

    def test_external_service_error(self) -> None:
        """ExternalServiceError should default to HTTP 502."""
        exc = ExternalServiceError(service_name="Google Routes")
        self.assertEqual(exc.http_status, 502)
        self.assertEqual(exc.service_name, "Google Routes")

    def test_database_error(self) -> None:
        """DatabaseError should default to HTTP 500."""
        exc = DatabaseError()
        self.assertEqual(exc.http_status, 500)

    def test_inheritance_chain(self) -> None:
        """All custom exceptions should be subclasses of CarbonWiseError."""
        self.assertTrue(issubclass(ValidationError, CarbonWiseError))
        self.assertTrue(issubclass(CalculationError, CarbonWiseError))
        self.assertTrue(issubclass(ResourceNotFoundError, CarbonWiseError))
        self.assertTrue(issubclass(ExternalServiceError, CarbonWiseError))
        self.assertTrue(issubclass(DatabaseError, CarbonWiseError))


# ===================================================================
# Unit Tests — Input Sanitization
# ===================================================================


class TestSanitizer(unittest.TestCase):
    """Test input sanitization utility functions."""

    def test_sanitize_text_strips_control_chars(self) -> None:
        """Control characters should be removed from text input."""
        dirty = "Hello\x00World\x0bTest"
        self.assertEqual(sanitize_text(dirty), "HelloWorldTest")

    def test_sanitize_text_max_length(self) -> None:
        """Text exceeding max_length should be truncated."""
        long_text = "A" * 1000
        result = sanitize_text(long_text, max_length=50)
        self.assertEqual(len(result), 50)

    def test_sanitize_text_strips_whitespace(self) -> None:
        """Leading and trailing whitespace should be trimmed."""
        self.assertEqual(sanitize_text("  hello  "), "hello")

    def test_sanitize_user_id(self) -> None:
        """Only alphanumerics, underscores, hyphens, dots should remain."""
        self.assertEqual(sanitize_user_id("user@123!"), "user123")
        self.assertEqual(sanitize_user_id("valid_user-1.0"), "valid_user-1.0")
        # Long IDs should be truncated to 100 chars
        self.assertLessEqual(len(sanitize_user_id("a" * 200)), 100)

    def test_clamp_float(self) -> None:
        """Numeric values should be clamped to [minimum, maximum]."""
        self.assertEqual(clamp_float(50.0, minimum=0, maximum=100), 50.0)
        self.assertEqual(clamp_float(-10.0, minimum=0, maximum=100), 0.0)
        self.assertEqual(clamp_float(200.0, minimum=0, maximum=100), 100.0)

    def test_clamp_float_nan(self) -> None:
        """NaN input should raise ValueError."""
        import math

        with self.assertRaises(ValueError):
            clamp_float(math.nan)

    def test_normalize_travel_mode(self) -> None:
        """Common aliases should map to canonical mode names."""
        self.assertEqual(normalize_travel_mode("driving"), "car")
        self.assertEqual(normalize_travel_mode("cycling"), "bicycle")
        self.assertEqual(normalize_travel_mode("walking"), "walk")
        self.assertEqual(normalize_travel_mode("subway"), "train")
        self.assertEqual(normalize_travel_mode("car"), "car")

    def test_normalize_diet_type(self) -> None:
        """Common diet aliases should map to canonical names."""
        self.assertEqual(normalize_diet_type("plant-based"), "vegan")
        self.assertEqual(normalize_diet_type("omnivore"), "average")
        self.assertEqual(normalize_diet_type("pescatarian"), "no_beef")
        self.assertEqual(normalize_diet_type("vegan"), "vegan")


# ===================================================================
# Mock-based Tests — RoutesServiceClient
# ===================================================================


class TestRoutesServiceClient(unittest.TestCase):
    """Mock-based tests validating Google Routes API and fallback flow."""

    @patch("services.google_services.requests.post")
    def test_calculate_route_api_success(self, mock_post) -> None:
        """Successful API response should return parsed route data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "routes": [
                {
                    "distanceMeters": 16093,  # ~10 miles
                    "duration": "900s",
                    "travelAdvisory": {
                        "fuelConsumptionMicroliters": 1200000
                    },
                }
            ]
        }
        mock_post.return_value = mock_response

        client = RoutesServiceClient()
        client.api_key = "dummy_api_key"

        result = client.calculate_route(
            "San Francisco, CA", "Oakland, CA", "car"
        )
        self.assertEqual(result["distance_miles"], 10.0)
        self.assertEqual(result["duration_seconds"], 900)
        self.assertTrue(result["eco_friendly"])
        self.assertEqual(result["source"], "google_routes_api")

    @patch("services.google_services.requests.post")
    def test_calculate_route_api_failure_fallback(self, mock_post) -> None:
        """API 500 error should trigger simulation fallback."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        client = RoutesServiceClient()
        client.api_key = "dummy_api_key"

        result = client.calculate_route("New York, NY", "Boston, MA", "car")
        self.assertEqual(result["source"], "simulated_fallback")
        self.assertGreater(result["distance_miles"], 0)

    def test_calculate_route_missing_key_fallback(self) -> None:
        """Missing API key should trigger simulation fallback."""
        client = RoutesServiceClient()
        client.api_key = None

        result = client.calculate_route("New York, NY", "Boston, MA", "car")
        self.assertEqual(result["source"], "simulated_fallback")
        self.assertGreater(result["distance_miles"], 0)

    def test_calculate_route_flight_simulation(self) -> None:
        """Flight mode should always bypass API and simulate."""
        client = RoutesServiceClient()
        client.api_key = "dummy_api_key"
        result = client.calculate_route(
            "New York, NY", "London, UK", "flight"
        )
        self.assertEqual(result["source"], "simulated_fallback")
        speed_mph = 500.0
        expected_duration = int(
            (result["distance_miles"] / speed_mph) * 3600
        )
        self.assertEqual(result["duration_seconds"], expected_duration)

    def test_calculate_route_empty_inputs(self) -> None:
        """Empty origin or destination should raise ValueError."""
        client = RoutesServiceClient()
        with self.assertRaises(ValueError):
            client.calculate_route("", "Boston, MA", "car")
        with self.assertRaises(ValueError):
            client.calculate_route("New York, NY", "", "car")


# ===================================================================
# Mock-based Tests — FirestoreRepository
# ===================================================================


class TestFirestoreRepository(unittest.TestCase):
    """Mock-based and local-fallback test suite for user logging repositories."""

    def setUp(self) -> None:
        self.temp_db_path = "test_local_db.json"
        Config.LOCAL_DB_PATH = self.temp_db_path

    def tearDown(self) -> None:
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_local_fallback_crud(self) -> None:
        """Full CRUD cycle using local JSON database fallback."""
        with patch("services.google_services.FIRESTORE_AVAILABLE", False):
            repo = FirestoreRepository()
            self.assertTrue(repo.use_fallback)
            self.assertTrue(os.path.exists(self.temp_db_path))

            # Save user log
            log_data = {
                "total_co2": 15.5,
                "timestamp": "2026-06-16T12:00:00Z",
            }
            self.assertTrue(repo.save_user_log("user_999", log_data))

            # Retrieve user logs
            logs = repo.get_user_logs("user_999")
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["total_co2"], 15.5)

            # Profile CRUD
            profile_data = {"preferred_mode": "EV"}
            self.assertTrue(repo.save_user_profile("user_999", profile_data))
            profile = repo.get_user_profile("user_999")
            self.assertEqual(profile["preferred_mode"], "EV")

            # Actions CRUD
            action_data = {
                "action": "led_lights",
                "carbon_offset_kg": 0.5,
                "timestamp": "2026-06-16T12:00:00Z",
            }
            self.assertTrue(repo.save_daily_action("user_999", action_data))
            actions = repo.get_daily_actions("user_999")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action"], "led_lights")

            # Clear Actions
            self.assertTrue(repo.clear_user_actions("user_999"))
            self.assertEqual(len(repo.get_daily_actions("user_999")), 0)

    def test_live_firestore_exception_fallback(self) -> None:
        """Firestore errors should gracefully fall back to local DB."""
        with patch("services.google_services.FIRESTORE_AVAILABLE", True):
            mock_db = MagicMock()
            mock_db.collection.side_effect = Exception(
                "Firestore API Disabled 403"
            )

            with patch(
                "services.google_services.firestore.client",
                return_value=mock_db,
            ):
                with patch(
                    "services.google_services.firebase_admin._apps", True
                ):
                    repo = FirestoreRepository()
                    self.assertFalse(repo.use_fallback)
                    self.assertEqual(repo.db, mock_db)

                    log_data = {
                        "total_co2": 20.0,
                        "timestamp": "2026-06-16T12:00:00Z",
                    }
                    self.assertTrue(
                        repo.save_user_log("user_fallback_test", log_data)
                    )

                    logs = repo.get_user_logs("user_fallback_test")
                    self.assertEqual(len(logs), 1)
                    self.assertEqual(logs[0]["total_co2"], 20.0)

                    action_data = {
                        "action": "walk",
                        "carbon_offset_kg": 0.5,
                    }
                    self.assertTrue(
                        repo.save_daily_action(
                            "user_fallback_test", action_data
                        )
                    )

                    actions = repo.get_daily_actions("user_fallback_test")
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(actions[0]["action"], "walk")

    def test_clear_user_logs(self) -> None:
        """Clearing logs should empty the user's log list."""
        with patch("services.google_services.FIRESTORE_AVAILABLE", False):
            repo = FirestoreRepository()
            repo.save_user_log("clear_test", {"total_co2": 5.0})
            self.assertEqual(len(repo.get_user_logs("clear_test")), 1)
            self.assertTrue(repo.clear_user_logs("clear_test"))
            self.assertEqual(len(repo.get_user_logs("clear_test")), 0)

    def test_nonexistent_user_returns_empty(self) -> None:
        """Querying a nonexistent user should return empty lists/dicts."""
        with patch("services.google_services.FIRESTORE_AVAILABLE", False):
            repo = FirestoreRepository()
            self.assertEqual(repo.get_user_logs("ghost"), [])
            self.assertEqual(repo.get_daily_actions("ghost"), [])
            self.assertEqual(repo.get_user_profile("ghost"), {})


# ===================================================================
# Integration Tests — FastAPI Endpoints
# ===================================================================


class TestAPIEndpoints(unittest.TestCase):
    """Integration tests for all FastAPI routes."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.temp_db_path = "test_endpoint_db.json"
        Config.LOCAL_DB_PATH = self.temp_db_path

        from main import db_repo

        self.original_db_path = db_repo.local_db_path
        db_repo.local_db_path = self.temp_db_path
        db_repo.use_fallback = True
        db_repo._init_local_db()

        self.firestore_patcher = patch(
            "services.google_services.FIRESTORE_AVAILABLE", False
        )
        self.firestore_patcher.start()

    def tearDown(self) -> None:
        self.firestore_patcher.stop()
        from main import db_repo

        db_repo.local_db_path = self.original_db_path
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    # --- Health Check ---

    def test_health_endpoint(self) -> None:
        """GET /api/health should return status and service info."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)
        self.assertIn("services", data)
        self.assertIn("google_routes", data["services"])
        self.assertIn("firestore", data["services"])

    # --- Calculate Endpoint ---

    def test_calculate_endpoint(self) -> None:
        """POST /api/calculate should return correct CO₂ calculations."""
        payload = {
            "user_id": "test_user_api",
            "electricity_kwh": 10.0,
            "gas_m3": 2.0,
            "transport": [
                {"distance": 15.0, "mode": "car", "vehicle_type": "hybrid"}
            ],
            "diet_type": "vegetarian",
            "diet_days": 1,
            "waste_kg": 2.0,
            "waste_recycling_rate": 0.5,
        }
        response = self.client.post("/api/calculate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["calculations"]["total_co2"], 16.16)

    def test_calculate_endpoint_with_net_co2(self) -> None:
        """Net CO₂ should deduct today's logged green-action offsets."""
        # Log an action first
        action_payload = {
            "user_id": "test_net_user",
            "action": "public_transit",
            "title": "Took Public Transit",
            "carbon_offset_kg": 1.8,
        }
        self.client.post("/api/action", json=action_payload)

        # Calculate emissions
        payload = {
            "user_id": "test_net_user",
            "electricity_kwh": 5.0,
            "gas_m3": 0.0,
            "transport": [],
            "diet_type": "vegan",
            "diet_days": 1,
            "waste_kg": 0.0,
            "waste_recycling_rate": 0.0,
        }
        response = self.client.post("/api/calculate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("net_co2", data["calculations"])
        # Total = 5 × 0.385 + 4.1 = 6.025; Net = 6.025 − 1.8 = 4.225
        self.assertEqual(data["calculations"]["net_co2"], 4.225)

        # Verify logs endpoint also returns net_co2
        logs_resp = self.client.get("/api/logs?user_id=test_net_user")
        self.assertEqual(logs_resp.status_code, 200)
        logs = logs_resp.json()
        self.assertEqual(logs[0]["net_co2"], 4.225)

    # --- Logs Endpoint ---

    def test_logs_endpoint(self) -> None:
        """GET /api/logs should return saved calculation history."""
        payload = {
            "user_id": "test_user_logs",
            "electricity_kwh": 5.0,
            "gas_m3": 0.0,
            "transport": [],
            "diet_type": "vegan",
            "diet_days": 1,
            "waste_kg": 0.0,
            "waste_recycling_rate": 0.0,
        }
        self.client.post("/api/calculate", json=payload)

        response = self.client.get("/api/logs?user_id=test_user_logs")
        self.assertEqual(response.status_code, 200)
        logs = response.json()
        self.assertEqual(len(logs), 1)
        # 5 × 0.385 + 4.1 = 6.025
        self.assertEqual(logs[0]["total_co2"], 6.025)

    # --- Action Endpoint ---

    def test_action_endpoint(self) -> None:
        """POST/GET /api/action should persist and retrieve green actions."""
        payload = {
            "user_id": "test_user_action",
            "action": "meatless_meal",
            "title": "Meatless Meal",
            "carbon_offset_kg": 1.2,
        }
        response = self.client.post("/api/action", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        response = self.client.get("/api/action?user_id=test_user_action")
        self.assertEqual(response.status_code, 200)
        actions = response.json()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "meatless_meal")

        # Clear logs and actions
        response = self.client.delete("/api/logs?user_id=test_user_action")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/api/action?user_id=test_user_action")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 0)

    # --- Recommendations Endpoint ---

    def test_recommendations_endpoint(self) -> None:
        """GET /api/recommendations should return personalized insights."""
        resp = self.client.get(
            "/api/recommendations?user_id=test_recs_user"
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json()
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)
        self.assertIn("category", recs[0])
        self.assertIn("title", recs[0])
        self.assertIn("estimated_savings_kg", recs[0])

    # --- Static Asset Serving ---

    def test_static_assets_serving(self) -> None:
        """Static CSS and JS should serve with long-term cache headers."""
        resp_css = self.client.get("/style.css")
        self.assertEqual(resp_css.status_code, 200)
        self.assertIn(
            "max-age=31536000", resp_css.headers.get("Cache-Control", "")
        )

        resp_js = self.client.get("/app.js")
        self.assertEqual(resp_js.status_code, 200)
        self.assertIn(
            "max-age=31536000", resp_js.headers.get("Cache-Control", "")
        )

    # --- Security Headers ---

    def test_security_headers_present(self) -> None:
        """All security headers should be present on responses."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            resp.headers.get("X-Content-Type-Options"), "nosniff"
        )
        self.assertEqual(
            resp.headers.get("X-XSS-Protection"), "1; mode=block"
        )
        self.assertEqual(
            resp.headers.get("Referrer-Policy"),
            "strict-origin-when-cross-origin",
        )
        self.assertIn("Content-Security-Policy", resp.headers)

    def test_permissions_policy_header(self) -> None:
        """Permissions-Policy header should restrict browser features."""
        resp = self.client.get("/")
        self.assertIn("Permissions-Policy", resp.headers)
        pp = resp.headers.get("Permissions-Policy", "")
        self.assertIn("camera=()", pp)
        self.assertIn("microphone=()", pp)

    def test_hsts_header(self) -> None:
        """HSTS header should enforce HTTPS with long max-age."""
        resp = self.client.get("/")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        self.assertIn("max-age=", hsts)
        self.assertIn("includeSubDomains", hsts)

    def test_cors_origin_restriction(self) -> None:
        """Disallowed origins should not receive CORS headers."""
        resp = self.client.get(
            "/", headers={"Origin": "https://malicious.com"}
        )
        self.assertNotEqual(
            resp.headers.get("Access-Control-Allow-Origin"),
            "https://malicious.com",
        )

        resp = self.client.get(
            "/", headers={"Origin": "http://localhost:8000"}
        )
        self.assertEqual(
            resp.headers.get("Access-Control-Allow-Origin"),
            "http://localhost:8000",
        )

    # --- Input Validation ---

    def test_input_validation_edge_cases(self) -> None:
        """Invalid inputs should return proper validation errors."""
        # Extremely long origin address (Pydantic validates max_length=500)
        payload = {
            "origin": "A" * 501,
            "destination": "Test Destination",
            "travel_mode": "car",
        }
        response = self.client.post("/api/route", json=payload)
        self.assertEqual(response.status_code, 422)

        # Invalid negative numeric fields
        calc_payload = {
            "user_id": "test_validation_user",
            "electricity_kwh": -10.0,
        }
        response = self.client.post("/api/calculate", json=calc_payload)
        self.assertEqual(response.status_code, 422)

    def test_missing_user_id_returns_422(self) -> None:
        """Missing required user_id should return 422."""
        response = self.client.get("/api/logs")
        self.assertEqual(response.status_code, 422)


# ===================================================================
# Entry Point
# ===================================================================

if __name__ == "__main__":
    unittest.main()
