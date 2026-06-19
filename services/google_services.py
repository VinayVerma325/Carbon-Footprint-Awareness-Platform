"""
Google Cloud service integrations for the CarbonWise platform.

This module provides two service classes:

* :class:`RoutesServiceClient` — Wraps the Google Routes API v2 for real-time
  route distance and duration estimation.  Falls back to a deterministic
  simulation when the API key is missing or the service is unreachable.

* :class:`FirestoreRepository` — Implements the repository pattern over
  Google Cloud Firestore for user logs, actions, and profiles.  When
  Firestore credentials are unavailable, it transparently switches to a
  thread-safe local JSON file database.

Design decisions:
    • **Graceful degradation** — Both classes are designed to *never* crash
      the application.  External failures are caught, logged, and handled
      via internal fallback paths.
    • **Thread safety** — ``FirestoreRepository`` guards all local-file I/O
      with a ``threading.RLock`` to prevent data corruption under concurrent
      request handling by Uvicorn worker threads.
    • **Zero mandatory cloud dependencies** — The ``firebase-admin`` SDK is
      imported conditionally; the application runs fully offline when it is
      not installed.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

import requests

from config import Config

logger = logging.getLogger("CarbonPlatformServices")

# ---------------------------------------------------------------------------
# Optional Firebase imports
# ---------------------------------------------------------------------------
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    FIRESTORE_AVAILABLE: bool = True
except ImportError:
    FIRESTORE_AVAILABLE = False
    logger.info(
        "Firebase Admin SDK not installed. Operating in Local JSON DB mode."
    )


# ---------------------------------------------------------------------------
# Google Routes API Client
# ---------------------------------------------------------------------------


class RoutesServiceClient:
    """Service client for the Google Routes API (v2).

    Provides robust error handling and a deterministic simulation fallback
    so that the frontend always receives a usable distance/duration response,
    even when the API is unconfigured or offline.

    Attributes:
        API_URL: Endpoint for Google Routes ``computeRoutes`` v2.
        api_key: Google Maps API key read from :class:`Config`.
    """

    API_URL: str = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(self) -> None:
        self.api_key: Optional[str] = Config.GOOGLE_MAPS_API_KEY

    def calculate_route(
        self,
        origin: str,
        destination: str,
        travel_mode: str = "DRIVE",
    ) -> Dict[str, Any]:
        """Calculate route details using Google Routes API v2.

        Args:
            origin: Starting location address or coordinates.
            destination: Ending location address or coordinates.
            travel_mode: Travel mode (e.g. ``DRIVE``, ``WALK``, ``BICYCLE``,
                ``TRANSIT``, ``flight``).

        Returns:
            Dictionary containing ``distance_miles``, ``duration_seconds``,
            ``eco_friendly`` flag, and ``source`` indicator.

        Raises:
            ValueError: If *origin* or *destination* is empty or exceeds
                500 characters.
        """
        if not origin or not destination:
            raise ValueError("Origin and destination addresses are required.")
        if len(origin) > 500 or len(destination) > 500:
            raise ValueError(
                "Origin and destination address strings must not exceed "
                "500 characters."
            )

        # Flight mode is not supported by Google Routes API — simulate directly
        if travel_mode.lower() == "flight":
            logger.info("Flight mode requested. Simulating route calculation.")
            return self._simulate_route(origin, destination, travel_mode)

        # Map frontend travel modes to Routes API travel modes
        mode_mapping: Dict[str, str] = {
            "car": "DRIVE",
            "bus": "TRANSIT",
            "train": "TRANSIT",
            "motorcycle": "DRIVE",
            "walk": "WALK",
            "bicycle": "BICYCLE",
        }
        api_mode = mode_mapping.get(travel_mode.lower(), "DRIVE")

        # If API key is missing, immediately fall back to simulation
        if not self.api_key:
            logger.info(
                "Google Maps API key missing. Simulating route calculation."
            )
            return self._simulate_route(origin, destination, travel_mode)

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "routes.distanceMeters,routes.duration,"
                "routes.travelAdvisory,routes.localizedValues"
            ),
        }

        body: Dict[str, Any] = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": api_mode,
        }

        # Add routing preference only for driving/two-wheeler
        if api_mode in ("DRIVE", "TWO_WHEELER"):
            body["routingPreference"] = "TRAFFIC_AWARE_OPTIMAL"
            body["requestedReferenceRoutes"] = ["FUEL_EFFICIENT"]

        try:
            response = requests.post(
                self.API_URL, headers=headers, json=body, timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                routes = data.get("routes", [])
                if routes:
                    primary_route = routes[0]
                    distance_meters = float(
                        primary_route.get("distanceMeters", 0)
                    )
                    duration_raw = primary_route.get("duration", "0s")
                    duration_seconds = int(
                        str(duration_raw).replace("s", "")
                    )

                    # 1 metre = 0.000621371 miles
                    distance_miles = round(
                        distance_meters * 0.000621371, 2
                    )

                    # Check for eco-friendly route metadata
                    eco_friendly = False
                    travel_advisory = primary_route.get(
                        "travelAdvisory", {}
                    )
                    if "fuelConsumptionMicroliters" in travel_advisory:
                        eco_friendly = True

                    return {
                        "distance_miles": distance_miles,
                        "duration_seconds": duration_seconds,
                        "eco_friendly": eco_friendly,
                        "source": "google_routes_api",
                    }

                logger.warning(
                    "No routes found in API response. "
                    "Falling back to simulation."
                )
                return self._simulate_route(
                    origin, destination, travel_mode
                )

            logger.error(
                "Google Routes API returned error status %d: %s",
                response.status_code,
                response.text,
            )
            return self._simulate_route(origin, destination, travel_mode)

        except Exception as exc:
            logger.error(
                "Failed to communicate with Google Routes API: %s",
                str(exc),
            )
            return self._simulate_route(origin, destination, travel_mode)

    def _simulate_route(
        self,
        origin: str,
        destination: str,
        travel_mode: str,
    ) -> Dict[str, Any]:
        """Provide a deterministic fallback simulation for offline mode.

        The simulated distance is derived from a hash of the origin and
        destination strings, ensuring reproducible results for the same
        input pair.

        Args:
            origin: Starting location string.
            destination: Ending location string.
            travel_mode: Canonical travel mode key.

        Returns:
            Simulated route dictionary with ``source`` set to
            ``"simulated_fallback"``.
        """
        hash_val = sum(ord(c) for c in (origin + destination))
        if travel_mode.lower() == "flight":
            simulated_distance = round((hash_val % 2500) + 100.5, 2)
        else:
            simulated_distance = round((hash_val % 450) + 5.5, 2)

        # Estimate duration based on typical speed for each mode (mph)
        speed_table: Dict[str, float] = {
            "walk": 3.0,
            "bicycle": 12.0,
            "bike": 12.0,
            "bus": 35.0,
            "train": 35.0,
            "flight": 500.0,
        }
        speed_mph = speed_table.get(travel_mode.lower(), 40.0)
        duration_seconds = int((simulated_distance / speed_mph) * 3600)

        return {
            "distance_miles": simulated_distance,
            "duration_seconds": duration_seconds,
            "eco_friendly": travel_mode.lower()
            in ("train", "bus", "bicycle", "walk"),
            "source": "simulated_fallback",
        }


# ---------------------------------------------------------------------------
# Firestore Repository (with local JSON fallback)
# ---------------------------------------------------------------------------


class FirestoreRepository:
    """Repository managing Firebase Firestore connectivity.

    Gracefully falls back to a thread-safe local JSON file when Firestore
    is unavailable (missing SDK, invalid credentials, or runtime errors).

    The local JSON database schema::

        {
            "logs":     { "<user_id>": [ ... ] },
            "actions":  { "<user_id>": [ ... ] },
            "profiles": { "<user_id>": { ... } }
        }

    Attributes:
        db: Live Firestore client, or ``None`` when using fallback.
        local_db_path: Path to the local JSON database file.
        use_fallback: ``True`` when operating in local-file mode.
    """

    def __init__(self) -> None:
        self.db: Any = None
        self.local_db_path: str = Config.LOCAL_DB_PATH
        self.use_fallback: bool = True
        self._lock = threading.RLock()

        if FIRESTORE_AVAILABLE:
            try:
                self._initialize_firebase()
            except Exception as exc:
                logger.warning(
                    "Unable to initialize live Firestore client: %s. "
                    "Falling back to local database.",
                    str(exc),
                )

        if self.use_fallback:
            self._init_local_db()

    def _initialize_firebase(self) -> None:
        """Attempt to initialize Firebase Admin SDK from available credentials.

        Tries, in order:
            1. ``FIREBASE_CREDENTIALS_JSON`` environment variable (inline JSON).
            2. ``GOOGLE_APPLICATION_CREDENTIALS`` file path.
            3. ``FIREBASE_PROJECT_ID`` only (for environments with ADC).
            4. Application Default Credentials (ADC).

        Raises:
            ValueError: If no valid credential source is found.
        """
        if not firebase_admin._apps:
            if Config.FIREBASE_CREDENTIALS_JSON:
                creds_dict = json.loads(Config.FIREBASE_CREDENTIALS_JSON)
                cred = credentials.Certificate(creds_dict)
                firebase_admin.initialize_app(cred)
                logger.info(
                    "Firebase Admin initialized via JSON credentials "
                    "env variable."
                )
            elif Config.GOOGLE_APPLICATION_CREDENTIALS:
                is_valid_cert = self._validate_service_account_file(
                    Config.GOOGLE_APPLICATION_CREDENTIALS
                )
                if is_valid_cert:
                    cred = credentials.Certificate(
                        Config.GOOGLE_APPLICATION_CREDENTIALS
                    )
                    firebase_admin.initialize_app(cred)
                    logger.info(
                        "Firebase Admin initialized via Google Application "
                        "Credentials file."
                    )
                elif Config.FIREBASE_PROJECT_ID:
                    firebase_admin.initialize_app(
                        options={"projectId": Config.FIREBASE_PROJECT_ID}
                    )
                    logger.info(
                        "Firebase Admin initialized with Project ID."
                    )
                else:
                    raise ValueError(
                        "Google Application Credentials file is an invalid "
                        "placeholder and no Project ID was configured."
                    )
            elif Config.FIREBASE_PROJECT_ID:
                firebase_admin.initialize_app(
                    options={"projectId": Config.FIREBASE_PROJECT_ID}
                )
                logger.info("Firebase Admin initialized with Project ID.")
            else:
                try:
                    firebase_admin.initialize_app()
                    logger.info(
                        "Firebase Admin initialized with default credentials."
                    )
                except Exception:
                    raise ValueError(
                        "No Firestore credentials configured."
                    )

        self.db = firestore.client()
        self.use_fallback = False
        logger.info("Successfully connected to live Firestore.")

    @staticmethod
    def _validate_service_account_file(path: str) -> bool:
        """Check whether a service-account JSON file is valid (not a placeholder).

        Args:
            path: Filesystem path to the service-account JSON file.

        Returns:
            ``True`` if the file exists, parses as JSON, and contains
            ``"type": "service_account"``.
        """
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    cert_data = json.load(f)
                    return bool(
                        cert_data and cert_data.get("type") == "service_account"
                    )
        except Exception:
            pass
        return False

    # -- Local JSON database helpers ----------------------------------------

    def _init_local_db(self) -> None:
        """Create the local JSON database file if it does not exist."""
        if not os.path.exists(self.local_db_path):
            with open(self.local_db_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"logs": {}, "actions": {}, "profiles": {}}, f, indent=4
                )
            logger.info(
                "Initialized local database file at %s", self.local_db_path
            )

    def _read_local_db(self) -> Dict[str, Any]:
        """Read and return the full local database contents.

        Returns:
            Parsed JSON dictionary, or an empty skeleton on read failure.
        """
        with self._lock:
            try:
                with open(self.local_db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error("Error reading local database: %s", str(exc))
                return {"logs": {}, "actions": {}, "profiles": {}}

    def _write_local_db(self, data: Dict[str, Any]) -> None:
        """Atomically write the full database contents to the local file.

        Args:
            data: Complete database dictionary to persist.
        """
        with self._lock:
            try:
                with open(self.local_db_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception as exc:
                logger.error("Error writing local database: %s", str(exc))

    # -- CRUD: User Logs ----------------------------------------------------

    def save_user_log(self, user_id: str, log_data: Dict[str, Any]) -> bool:
        """Persist a new carbon calculation log for a user.

        Args:
            user_id: Unique user identifier.
            log_data: Calculation result dictionary to store.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            if not self.use_fallback and self.db:
                self.db.collection("users").document(user_id).collection(
                    "logs"
                ).add(log_data)
                return True
        except Exception as exc:
            logger.error(
                "Error saving user log to Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                user_logs = db_data["logs"].setdefault(user_id, [])
                user_logs.append(log_data)
                self._write_local_db(db_data)
                return True
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return False

    def get_user_logs(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve all carbon logs for a user.

        Args:
            user_id: Unique user identifier.

        Returns:
            List of calculation log dictionaries, ordered by timestamp.
        """
        try:
            if not self.use_fallback and self.db:
                docs = (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("logs")
                    .order_by("timestamp")
                    .stream()
                )
                return [doc.to_dict() for doc in docs]
        except Exception as exc:
            logger.error(
                "Error getting user logs from Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                return db_data["logs"].get(user_id, [])
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return []

    def clear_user_logs(self, user_id: str) -> bool:
        """Delete all carbon calculation logs for a user.

        Args:
            user_id: Unique user identifier.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            if not self.use_fallback and self.db:
                docs = (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("logs")
                    .stream()
                )
                for doc in docs:
                    doc.reference.delete()
        except Exception as exc:
            logger.error(
                "Error clearing user logs from Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                if user_id in db_data["logs"]:
                    db_data["logs"][user_id] = []
                    self._write_local_db(db_data)
                return True
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return False

    # -- CRUD: Daily Actions ------------------------------------------------

    def save_daily_action(
        self, user_id: str, action_data: Dict[str, Any]
    ) -> bool:
        """Persist a daily green action completed by the user.

        Args:
            user_id: Unique user identifier.
            action_data: Action details including offset amount.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            if not self.use_fallback and self.db:
                self.db.collection("users").document(user_id).collection(
                    "actions"
                ).add(action_data)
                return True
        except Exception as exc:
            logger.error(
                "Error saving daily action to Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                user_actions = db_data["actions"].setdefault(user_id, [])
                user_actions.append(action_data)
                self._write_local_db(db_data)
                return True
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return False

    def get_daily_actions(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve all green actions logged by a user.

        Args:
            user_id: Unique user identifier.

        Returns:
            List of action dictionaries.
        """
        try:
            if not self.use_fallback and self.db:
                docs = (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("actions")
                    .stream()
                )
                return [doc.to_dict() for doc in docs]
        except Exception as exc:
            logger.error(
                "Error getting daily actions from Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                return db_data["actions"].get(user_id, [])
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return []

    def clear_user_actions(self, user_id: str) -> bool:
        """Delete all green actions for a user.

        Args:
            user_id: Unique user identifier.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            if not self.use_fallback and self.db:
                docs = (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("actions")
                    .stream()
                )
                for doc in docs:
                    doc.reference.delete()
        except Exception as exc:
            logger.error(
                "Error clearing user actions from Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                if user_id in db_data["actions"]:
                    db_data["actions"][user_id] = []
                    self._write_local_db(db_data)
                return True
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return False

    # -- CRUD: User Profile -------------------------------------------------

    def save_user_profile(
        self, user_id: str, profile_data: Dict[str, Any]
    ) -> bool:
        """Save or overwrite user configuration settings.

        Args:
            user_id: Unique user identifier.
            profile_data: Profile/settings dictionary.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            if not self.use_fallback and self.db:
                (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("profile")
                    .document("settings")
                    .set(profile_data)
                )
                return True
        except Exception as exc:
            logger.error(
                "Error saving user profile to Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                db_data["profiles"][user_id] = profile_data
                self._write_local_db(db_data)
                return True
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return False

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Retrieve user configuration settings.

        Args:
            user_id: Unique user identifier.

        Returns:
            Profile dictionary, or empty dict if none exists.
        """
        try:
            if not self.use_fallback and self.db:
                doc_ref = (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("profile")
                    .document("settings")
                )
                doc = doc_ref.get()
                return doc.to_dict() if doc.exists else {}
        except Exception as exc:
            logger.error(
                "Error getting user profile from Firestore: %s. "
                "Falling back to local DB.",
                str(exc),
            )

        try:
            with self._lock:
                db_data = self._read_local_db()
                return db_data["profiles"].get(user_id, {})
        except Exception as local_err:
            logger.error("Local DB fallback failed: %s", str(local_err))
            return {}
