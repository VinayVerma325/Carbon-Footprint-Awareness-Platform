import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path to allow core and services modules to be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import components
from core.calculator import CarbonCalculator, RecommendationEngine
from services.google_services import RoutesServiceClient, FirestoreRepository
from config import Config
from fastapi.testclient import TestClient
from main import app


class TestCarbonCalculator(unittest.TestCase):
    """Granular unit tests for the carbon footprint conversion engines."""

    def test_electricity_calculations(self) -> None:
        # 100 kWh * 0.385 = 38.5 kg CO2
        self.assertEqual(CarbonCalculator.calculate_electricity(100.0), 38.5)
        self.assertEqual(CarbonCalculator.calculate_electricity(0.0), 0.0)
        
        with self.assertRaises(ValueError):
            CarbonCalculator.calculate_electricity(-10.0)

    def test_gas_calculations(self) -> None:
        # 50 m3 * 2.03 = 101.5 kg CO2
        self.assertEqual(CarbonCalculator.calculate_gas(50.0), 101.5)
        self.assertEqual(CarbonCalculator.calculate_gas(0.0), 0.0)
        
        with self.assertRaises(ValueError):
            CarbonCalculator.calculate_gas(-5.0)

    def test_transport_calculations(self) -> None:
        # Car - petrol: 10 miles * 0.404 = 4.04 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(10.0, "car", "petrol"), 4.04)
        
        # Car - electric: 10 miles * 0.050 = 0.50 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(10.0, "car", "electric"), 0.50)
        
        # Bus: 20 miles * 0.100 = 2.00 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(20.0, "bus"), 2.00)
        
        # Train: 50 miles * 0.050 = 2.50 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(50.0, "train"), 2.50)
        
        # Flight short (<300 miles): 200 miles * 0.250 = 50.00 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(200.0, "flight"), 50.00)
        
        # Flight long (>=300 miles): 500 miles * 0.150 = 75.00 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(500.0, "flight"), 75.00)
        
        # Bicycle: 10 miles * 0.0 = 0.0 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(10.0, "bicycle"), 0.0)
        
        # Walk: 5 miles * 0.0 = 0.0 kg CO2
        self.assertEqual(CarbonCalculator.calculate_transport(5.0, "walk"), 0.0)

        with self.assertRaises(ValueError):
            CarbonCalculator.calculate_transport(-20.0, "car")

    def test_diet_calculations(self) -> None:
        # Vegan: 7 days * 4.1 = 28.7 kg CO2
        self.assertEqual(CarbonCalculator.calculate_diet(7, "vegan"), 28.7)
        # Heavy meat: 3 days * 9.0 = 27.0 kg CO2
        self.assertEqual(CarbonCalculator.calculate_diet(3, "heavy_meat"), 27.0)
        # Invalid key falls back to average: 1 day * 6.8 = 6.8 kg CO2
        self.assertEqual(CarbonCalculator.calculate_diet(1, "invalid_diet"), 6.8)

        with self.assertRaises(ValueError):
            CarbonCalculator.calculate_diet(-1, "vegan")

    def test_waste_calculations(self) -> None:
        # 10 kg waste, 30% recycled (3kg recycled, 7kg landfill)
        # (7 * 0.500) + (3 * 0.050) = 3.5 + 0.15 = 3.65 kg CO2
        self.assertEqual(CarbonCalculator.calculate_waste(10.0, 0.3), 3.65)
        self.assertEqual(CarbonCalculator.calculate_waste(10.0, 1.0), 0.50)
        self.assertEqual(CarbonCalculator.calculate_waste(10.0, 0.0), 5.0)

        with self.assertRaises(ValueError):
            CarbonCalculator.calculate_waste(-1.0, 0.5)
        with self.assertRaises(ValueError):
            CarbonCalculator.calculate_waste(10.0, 1.2)

    def test_total_calculation_aggregator(self) -> None:
        inputs = {
            "electricity_kwh": 10.0,
            "gas_m3": 2.0,
            "transport": [
                {"distance": 15.0, "mode": "car", "vehicle_type": "hybrid"},
                {"distance": 5.0, "mode": "walk"}
            ],
            "diet_type": "vegetarian",
            "diet_days": 1,
            "waste_kg": 2.0,
            "waste_recycling_rate": 0.5
        }
        
        # calc parts:
        # electricity: 10 * 0.385 = 3.85
        # gas: 2 * 2.03 = 4.06
        # transport 1: 15 * 0.200 = 3.00
        # transport 2: 5 * 0.0 = 0.0 (walk is zero-emission mode)
        # diet: 1 * 4.7 (vegetarian) = 4.7
        # waste: 2 kg, 0.5 recycling (1kg landfill * 0.5 + 1kg recycle * 0.05 = 0.55)
        # total = 3.85 + 4.06 + 3.00 + 0.0 + 4.7 + 0.55 = 16.16
        res = CarbonCalculator.calculate_total(inputs)
        self.assertEqual(res["electricity_co2"], 3.85)
        self.assertEqual(res["gas_co2"], 4.06)
        self.assertEqual(res["diet_co2"], 4.7)
        self.assertEqual(res["waste_co2"], 0.55)
        self.assertEqual(res["total_co2"], 16.16)


class TestRecommendationEngine(unittest.TestCase):
    """Unit tests for the pattern analysis and recommendation generator."""

    def test_recommendation_trends(self) -> None:
        # Mock high transport emissions
        user_data = {
            "electricity_kwh": 2.0,
            "gas_m3": 0.0,
            "transport": [{"distance": 50.0, "mode": "car", "vehicle_type": "petrol"}], # 20.2 kg CO2
            "diet_type": "vegan", # 4.1 kg CO2
            "waste_kg": 0.2,
            "waste_recycling_rate": 1.0 # 0.01 kg CO2
        }
        
        recs = RecommendationEngine.analyze_and_recommend(user_data, [])
        categories = [r["category"] for r in recs]
        
        # Since transport is high (20.2 > 3.0), we expect transport recommendation
        self.assertIn("transport", categories)
        # vegan diet is low (4.1 < 4.5), no diet recommendation
        self.assertNotIn("diet", categories)

    def test_all_sustainable_default_nudge(self) -> None:
        # All inputs are low/sustainable
        user_data = {
            "electricity_kwh": 2.0, # 2.0 * 0.385 = 0.77 (< 2.5)
            "gas_m3": 0.0,
            "transport": [{"distance": 2.0, "mode": "car", "vehicle_type": "electric"}], # 2 * 0.05 = 0.1 (< 3.0)
            "diet_type": "vegan", # 4.1 (< 4.5)
            "waste_kg": 0.2,
            "waste_recycling_rate": 0.9 # 0.18 recycled, 0.02 landfill -> 0.02*0.5 + 0.18*0.05 = 0.019 (< 0.2)
        }
        recs = RecommendationEngine.analyze_and_recommend(user_data, [])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["category"], "general")
        self.assertEqual(recs[0]["title"], "Maintain Your Green Habits!")


class TestRoutesServiceClient(unittest.TestCase):
    """Mock-based tests validating Google Routes API connection and simulated fallback flow."""

    @patch("services.google_services.requests.post")
    def test_calculate_route_api_success(self, mock_post) -> None:
        # Mock API response JSON structure
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "routes": [
                {
                    "distanceMeters": 16093,  # ~10 miles
                    "duration": "900s",
                    "travelAdvisory": {
                        "fuelConsumptionMicroliters": 1200000
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Instantiate with a temporary dummy key
        client = RoutesServiceClient()
        client.api_key = "dummy_api_key"
        
        result = client.calculate_route("San Francisco, CA", "Oakland, CA", "car")
        
        self.assertEqual(result["distance_miles"], 10.0)
        self.assertEqual(result["duration_seconds"], 900)
        self.assertTrue(result["eco_friendly"])
        self.assertEqual(result["source"], "google_routes_api")

    @patch("services.google_services.requests.post")
    def test_calculate_route_api_failure_fallback(self, mock_post) -> None:
        # Mock API returning a 500 error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        client = RoutesServiceClient()
        client.api_key = "dummy_api_key"
        
        # Calculation should not crash; it should fall back to simulation
        result = client.calculate_route("New York, NY", "Boston, MA", "car")
        self.assertEqual(result["source"], "simulated_fallback")
        self.assertGreater(result["distance_miles"], 0)

    def test_calculate_route_missing_key_fallback(self) -> None:
        client = RoutesServiceClient()
        client.api_key = None  # Ensure no key
        
        result = client.calculate_route("New York, NY", "Boston, MA", "car")
        self.assertEqual(result["source"], "simulated_fallback")
        self.assertGreater(result["distance_miles"], 0)

    def test_calculate_route_flight_simulation(self) -> None:
        client = RoutesServiceClient()
        # Flight mode should bypass standard route and simulate immediately
        client.api_key = "dummy_api_key"
        result = client.calculate_route("New York, NY", "London, UK", "flight")
        self.assertEqual(result["source"], "simulated_fallback")
        # Assert flight speed matches 500 mph
        speed_mph = 500.0
        expected_duration = int((result["distance_miles"] / speed_mph) * 3600)
        self.assertEqual(result["duration_seconds"], expected_duration)


class TestFirestoreRepository(unittest.TestCase):
    """Mock-based and local-fallback test suite for user logging repositories."""

    def setUp(self) -> None:
        self.temp_db_path = "test_local_db.json"
        # Force config path
        Config.LOCAL_DB_PATH = self.temp_db_path
        
    def tearDown(self) -> None:
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_local_fallback_crud(self) -> None:
        # Force fallback by ensuring FIRESTORE_AVAILABLE is False-like or DB doesn't init
        with patch("services.google_services.FIRESTORE_AVAILABLE", False):
            repo = FirestoreRepository()
            self.assertTrue(repo.use_fallback)
            self.assertTrue(os.path.exists(self.temp_db_path))
            
            # Save user log
            log_data = {"total_co2": 15.5, "timestamp": "2026-06-16T12:00:00Z"}
            save_status = repo.save_user_log("user_999", log_data)
            self.assertTrue(save_status)
            
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
            action_data = {"action": "led_lights", "carbon_offset_kg": 0.5, "timestamp": "2026-06-16T12:00:00Z"}
            self.assertTrue(repo.save_daily_action("user_999", action_data))
            actions = repo.get_daily_actions("user_999")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action"], "led_lights")
            
            # Clear Actions
            self.assertTrue(repo.clear_user_actions("user_999"))
            self.assertEqual(len(repo.get_daily_actions("user_999")), 0)

    def test_live_firestore_exception_fallback(self) -> None:
        with patch("services.google_services.FIRESTORE_AVAILABLE", True):
            mock_db = MagicMock()
            mock_db.collection.side_effect = Exception("Firestore API Disabled 403")
            
            with patch("services.google_services.firestore.client", return_value=mock_db):
                with patch("services.google_services.firebase_admin._apps", True):
                    repo = FirestoreRepository()
                    self.assertFalse(repo.use_fallback)
                    self.assertEqual(repo.db, mock_db)
                    
                    log_data = {"total_co2": 20.0, "timestamp": "2026-06-16T12:00:00Z"}
                    save_status = repo.save_user_log("user_fallback_test", log_data)
                    self.assertTrue(save_status)
                    
                    logs = repo.get_user_logs("user_fallback_test")
                    self.assertEqual(len(logs), 1)
                    self.assertEqual(logs[0]["total_co2"], 20.0)
                    
                    action_data = {"action": "walk", "carbon_offset_kg": 0.5}
                    self.assertTrue(repo.save_daily_action("user_fallback_test", action_data))
                    
                    actions = repo.get_daily_actions("user_fallback_test")
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(actions[0]["action"], "walk")


class TestAPIEndpoints(unittest.TestCase):
    """Integration tests for the FastAPI routes."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.temp_db_path = "test_endpoint_db.json"
        Config.LOCAL_DB_PATH = self.temp_db_path
        
        # Patch the instantiated repository path in main app to use temp db
        from main import db_repo
        self.original_db_path = db_repo.local_db_path
        db_repo.local_db_path = self.temp_db_path
        db_repo.use_fallback = True
        db_repo._init_local_db()
        
        # Force fallback database mode
        self.firestore_patcher = patch("services.google_services.FIRESTORE_AVAILABLE", False)
        self.firestore_patcher.start()

    def tearDown(self) -> None:
        self.firestore_patcher.stop()
        from main import db_repo
        db_repo.local_db_path = self.original_db_path
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_calculate_endpoint(self) -> None:
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
            "waste_recycling_rate": 0.5
        }
        response = self.client.post("/api/calculate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["calculations"]["total_co2"], 16.16)

    def test_logs_endpoint(self) -> None:
        # First save a log
        payload = {
            "user_id": "test_user_logs",
            "electricity_kwh": 5.0,
            "gas_m3": 0.0,
            "transport": [],
            "diet_type": "vegan",
            "diet_days": 1,
            "waste_kg": 0.0,
            "waste_recycling_rate": 0.0
        }
        self.client.post("/api/calculate", json=payload)

        # Retrieve logs
        response = self.client.get("/api/logs?user_id=test_user_logs")
        self.assertEqual(response.status_code, 200)
        logs = response.json()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["total_co2"], 6.025)  # 5*0.385 + 4.1 = 1.925 + 4.1 = 6.025

    def test_action_endpoint(self) -> None:
        payload = {
            "user_id": "test_user_action",
            "action": "meatless_meal",
            "title": "Meatless Meal",
            "carbon_offset_kg": 1.2
        }
        response = self.client.post("/api/action", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        # Get actions
        response = self.client.get("/api/action?user_id=test_user_action")
        self.assertEqual(response.status_code, 200)
        actions = response.json()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "meatless_meal")

        # Clear logs and actions
        response = self.client.delete("/api/logs?user_id=test_user_action")
        self.assertEqual(response.status_code, 200)
        
        # Verify actions are cleared
        response = self.client.get("/api/action?user_id=test_user_action")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 0)

    def test_static_assets_serving(self) -> None:
        # Check style.css serving
        resp_css = self.client.get("/style.css")
        self.assertEqual(resp_css.status_code, 200)
        self.assertIn("max-age=31536000", resp_css.headers.get("Cache-Control", ""))

        # Check app.js serving
        resp_js = self.client.get("/app.js")
        self.assertEqual(resp_js.status_code, 200)
        self.assertIn("max-age=31536000", resp_js.headers.get("Cache-Control", ""))


if __name__ == "__main__":
    unittest.main()
