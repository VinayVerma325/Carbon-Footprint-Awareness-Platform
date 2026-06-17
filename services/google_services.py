import json
import logging
import os
import requests
from typing import Dict, Any, List, Optional
from config import Config

logger = logging.getLogger("CarbonPlatformServices")

# Optional imports for Google Cloud / Firebase Admin
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False
    logger.info("Firebase Admin SDK not installed. Operating in Local JSON DB mode.")


class RoutesServiceClient:
    """Service client for the Google Routes API (v2). Includes robust error handling and simulation fallbacks."""
    
    API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
    
    def __init__(self) -> None:
        self.api_key = Config.GOOGLE_MAPS_API_KEY

    def calculate_route(self, origin: str, destination: str, travel_mode: str = "DRIVE") -> Dict[str, Any]:
        """
        Calculate route details using Google Routes API v2.
        
        Args:
            origin: Starting location address or coordinates.
            destination: Ending location address or coordinates.
            travel_mode: Travel mode (e.g., DRIVE, WALK, BICYCLE, TRANSIT).
            
        Returns:
            Dict containing distance (miles), duration (seconds), and carbon efficiency details.
        """
        if not origin or not destination:
            raise ValueError("Origin and destination addresses are required.")
            
        # Map frontend travel modes to Routes API travel modes
        mode_mapping = {
            "car": "DRIVE",
            "bus": "TRANSIT",
            "train": "TRANSIT",
            "motorcycle": "DRIVE",
            "walk": "WALK",
            "bicycle": "BICYCLE"
        }
        api_mode = mode_mapping.get(travel_mode.lower(), "DRIVE")
        
        # If API key is missing, immediately fall back to simulation
        if not self.api_key:
            logger.info("Google Maps API key missing. Simulating route calculation.")
            return self._simulate_route(origin, destination, travel_mode)
            
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.travelAdvisory,routes.localizedValues"
        }
        
        body: Dict[str, Any] = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": api_mode,
        }
        
        # Add routing preference only for driving/two-wheeler
        if api_mode in ["DRIVE", "TWO_WHEELER"]:
            body["routingPreference"] = "TRAFFIC_AWARE_OPTIMAL"
            body["requestedReferenceRoutes"] = ["FUEL_EFFICIENT"]
            
        try:
            response = requests.post(self.API_URL, headers=headers, json=body, timeout=10)
            if response.status_code == 200:
                data = response.json()
                routes = data.get("routes", [])
                if routes:
                    primary_route = routes[0]
                    distance_meters = float(primary_route.get("distanceMeters", 0))
                    duration_seconds = int(primary_route.get("duration", "0s").replace("s", ""))
                    
                    # 1 meter = 0.000621371 miles
                    distance_miles = round(distance_meters * 0.000621371, 2)
                    
                    # Check for eco-friendly route metadata
                    eco_friendly = False
                    travel_advisory = primary_route.get("travelAdvisory", {})
                    if "fuelConsumptionMicroliters" in travel_advisory:
                        eco_friendly = True
                        
                    return {
                        "distance_miles": distance_miles,
                        "duration_seconds": duration_seconds,
                        "eco_friendly": eco_friendly,
                        "source": "google_routes_api"
                    }
                else:
                    logger.warning("No routes found in API response. Falling back to simulation.")
                    return self._simulate_route(origin, destination, travel_mode)
            else:
                logger.error(f"Google Routes API returned error status {response.status_code}: {response.text}")
                return self._simulate_route(origin, destination, travel_mode)
                
        except Exception as e:
            logger.error(f"Failed to communicate with Google Routes API: {str(e)}")
            return self._simulate_route(origin, destination, travel_mode)

    def _simulate_route(self, origin: str, destination: str, travel_mode: str) -> Dict[str, Any]:
        """Provide a secure fallback simulation for offline mode and missing API keys."""
        # Simple deterministic distance simulation based on characters
        hash_val = sum(ord(c) for c in (origin + destination))
        simulated_distance = round((hash_val % 450) + 5.5, 2)
        
        # Estimate duration (average 45 mph for driving, 3 mph walking, etc.)
        speed_mph = 40.0
        if travel_mode.lower() in ["walk", "bicycle"]:
            speed_mph = 10.0
        elif travel_mode.lower() in ["bus", "train"]:
            speed_mph = 35.0
            
        duration_seconds = int((simulated_distance / speed_mph) * 3600)
        
        return {
            "distance_miles": simulated_distance,
            "duration_seconds": duration_seconds,
            "eco_friendly": travel_mode.lower() in ["train", "bus", "bicycle", "walk"],
            "source": "simulated_fallback"
        }


class FirestoreRepository:
    """Repository managing Firebase Firestore connectivity. Gracefully falls back to local file storage."""

    def __init__(self) -> None:
        self.db = None
        self.local_db_path = Config.LOCAL_DB_PATH
        self.use_fallback = True

        if FIRESTORE_AVAILABLE:
            try:
                # Initialize Firebase SDK
                if not firebase_admin._apps:
                    if Config.FIREBASE_CREDENTIALS_JSON:
                        creds_dict = json.loads(Config.FIREBASE_CREDENTIALS_JSON)
                        cred = credentials.Certificate(creds_dict)
                        firebase_admin.initialize_app(cred)
                        logger.info("Firebase Admin initialized via JSON credentials env variable.")
                    elif Config.GOOGLE_APPLICATION_CREDENTIALS:
                        cred = credentials.Certificate(Config.GOOGLE_APPLICATION_CREDENTIALS)
                        firebase_admin.initialize_app(cred)
                        logger.info("Firebase Admin initialized via Google Application Credentials file.")
                    elif Config.FIREBASE_PROJECT_ID:
                        firebase_admin.initialize_app(options={"projectId": Config.FIREBASE_PROJECT_ID})
                        logger.info("Firebase Admin initialized with Project ID.")
                    else:
                        # Attempt default credentials
                        try:
                            firebase_admin.initialize_app()
                            logger.info("Firebase Admin initialized with default credentials.")
                        except Exception:
                            raise ValueError("No Firestore credentials configured.")

                self.db = firestore.client()
                self.use_fallback = False
                logger.info("Successfully connected to live Firestore.")
            except Exception as e:
                logger.warning(f"Unable to initialize live Firestore client: {str(e)}. Falling back to local database.")

        if self.use_fallback:
            self._init_local_db()

    def _init_local_db(self) -> None:
        """Initialize the local file database if it doesn't exist."""
        if not os.path.exists(self.local_db_path):
            with open(self.local_db_path, "w") as f:
                json.dump({"logs": {}, "actions": {}, "profiles": {}}, f, indent=4)
            logger.info(f"Initialized local database file at {self.local_db_path}")

    def _read_local_db(self) -> Dict[str, Any]:
        """Read data from local DB."""
        try:
            with open(self.local_db_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading local database: {str(e)}")
            return {"logs": {}, "actions": {}, "profiles": {}}

    def _write_local_db(self, data: Dict[str, Any]) -> None:
        """Write data to local DB."""
        try:
            with open(self.local_db_path, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error writing local database: {str(e)}")

    def save_user_log(self, user_id: str, log_data: Dict[str, Any]) -> bool:
        """Save a new carbon calculation log for a user."""
        try:
            if not self.use_fallback and self.db:
                self.db.collection("users").document(user_id).collection("logs").add(log_data)
                return True
        except Exception as e:
            logger.error(f"Error saving user log to Firestore: {str(e)}. Falling back to local DB.")
            
        try:
            db_data = self._read_local_db()
            user_logs = db_data["logs"].setdefault(user_id, [])
            user_logs.append(log_data)
            self._write_local_db(db_data)
            return True
        except Exception as local_err:
            logger.error(f"Local DB fallback failed: {str(local_err)}")
            return False

    def get_user_logs(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve all carbon logs for a user."""
        try:
            if not self.use_fallback and self.db:
                docs = self.db.collection("users").document(user_id).collection("logs").order_by("timestamp").stream()
                return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Error getting user logs from Firestore: {str(e)}. Falling back to local DB.")
            
        try:
            db_data = self._read_local_db()
            return db_data["logs"].get(user_id, [])
        except Exception as local_err:
            logger.error(f"Local DB fallback failed: {str(local_err)}")
            return []

    def save_daily_action(self, user_id: str, action_data: Dict[str, Any]) -> bool:
        """Save a daily action completed by the user (green habit)."""
        try:
            if not self.use_fallback and self.db:
                self.db.collection("users").document(user_id).collection("actions").add(action_data)
                return True
        except Exception as e:
            logger.error(f"Error saving daily action to Firestore: {str(e)}. Falling back to local DB.")
            
        try:
            db_data = self._read_local_db()
            user_actions = db_data["actions"].setdefault(user_id, [])
            user_actions.append(action_data)
            self._write_local_db(db_data)
            return True
        except Exception as local_err:
            logger.error(f"Local DB fallback failed: {str(local_err)}")
            return False

    def get_daily_actions(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve daily actions completed by the user."""
        try:
            if not self.use_fallback and self.db:
                docs = self.db.collection("users").document(user_id).collection("actions").stream()
                return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Error getting daily actions from Firestore: {str(e)}. Falling back to local DB.")
            
        try:
            db_data = self._read_local_db()
            return db_data["actions"].get(user_id, [])
        except Exception as local_err:
            logger.error(f"Local DB fallback failed: {str(local_err)}")
            return []

    def save_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> bool:
        """Save user configuration settings/profile."""
        try:
            if not self.use_fallback and self.db:
                self.db.collection("users").document(user_id).collection("profile").document("settings").set(profile_data)
                return True
        except Exception as e:
            logger.error(f"Error saving user profile to Firestore: {str(e)}. Falling back to local DB.")
            
        try:
            db_data = self._read_local_db()
            db_data["profiles"][user_id] = profile_data
            self._write_local_db(db_data)
            return True
        except Exception as local_err:
            logger.error(f"Local DB fallback failed: {str(local_err)}")
            return False

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Retrieve user configuration settings/profile."""
        try:
            if not self.use_fallback and self.db:
                doc_ref = self.db.collection("users").document(user_id).collection("profile").document("settings")
                doc = doc_ref.get()
                return doc.to_dict() if doc.exists else {}
        except Exception as e:
            logger.error(f"Error getting user profile from Firestore: {str(e)}. Falling back to local DB.")
            
        try:
            db_data = self._read_local_db()
            return db_data["profiles"].get(user_id, {})
        except Exception as local_err:
            logger.error(f"Local DB fallback failed: {str(local_err)}")
            return {}
