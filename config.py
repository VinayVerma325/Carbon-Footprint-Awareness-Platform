"""
Environment configuration manager for the CarbonWise platform.

Responsibilities:
    1. Load environment variables from a ``.env`` file (custom parser,
       no third-party dependency required).
    2. Expose all configuration values as typed class attributes on
       :class:`Config`.
    3. Validate critical credentials on import and log actionable warnings
       when the application will operate in degraded / fallback mode.

Security considerations:
    • API keys and credentials are **never** hardcoded — they are read
      exclusively from environment variables or ``.env`` (which is in
      ``.gitignore``).
    • The ``.env`` parser handles both ``KEY=VALUE`` and ``KEY:VALUE``
      formats and strips surrounding quotes.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

# ---------------------------------------------------------------------------
# Logging bootstrap
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("CarbonPlatformConfig")


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------


def load_dotenv() -> None:
    """Load environment variables from a ``.env`` file in the project root.

    Supports two delimiter styles (``=`` and ``:``), strips surrounding
    quotes from values, and silently skips blank lines and comments
    (lines starting with ``#``).

    This is intentionally a minimal, dependency-free implementation.
    """
    env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".env"
    )
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Split by '=' or ':'
                separator = "=" if "=" in line else ":"
                if separator in line:
                    parts = line.split(separator, 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    # Strip surrounding quotes
                    if (
                        val.startswith(('"', "'"))
                        and val.endswith(('"', "'"))
                        and len(val) >= 2
                    ):
                        val = val[1:-1]
                    if key:
                        os.environ[key] = val
        logger.info("Configurations loaded from .env file successfully.")
    except Exception as exc:
        logger.warning("Failed to load .env file: %s", str(exc))


# Load .env variables on module import
load_dotenv()


# ---------------------------------------------------------------------------
# Configuration class
# ---------------------------------------------------------------------------


class Config:
    """Centralized, secure environment configuration manager.

    All values are read from environment variables at class-definition time.
    Downstream modules import ``Config`` and access its class attributes
    directly (e.g. ``Config.GOOGLE_MAPS_API_KEY``).

    Attributes:
        ENV: Deployment environment name (``development`` | ``production``).
        GOOGLE_MAPS_API_KEY: Google Routes API key (``None`` if unset).
        FIREBASE_PROJECT_ID: GCP project ID for Firestore.
        FIREBASE_CREDENTIALS_JSON: Inline JSON credentials string.
        GOOGLE_APPLICATION_CREDENTIALS: Path to service-account key file.
        HOST: Server bind address (default ``0.0.0.0``).
        PORT: Server listen port (default ``8000``).
        LOCAL_DB_PATH: Path to the local JSON database fallback file.
        ALLOWED_ORIGINS: List of permitted CORS origins.
    """

    ENV: str = os.getenv("ENV", "development").lower()

    # Google Routes API Key — must come from environment only.
    # Never hardcode a real key here: this file is tracked by git.
    GOOGLE_MAPS_API_KEY: Optional[str] = os.getenv("GOOGLE_MAPS_API_KEY")

    # Firebase / Firestore Configurations
    FIREBASE_PROJECT_ID: Optional[str] = os.getenv("FIREBASE_PROJECT_ID")
    FIREBASE_CREDENTIALS_JSON: Optional[str] = os.getenv(
        "FIREBASE_CREDENTIALS_JSON"
    )
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "service-account.json"
    )

    # Resolve relative credentials path to absolute so Google SDK finds it
    if GOOGLE_APPLICATION_CREDENTIALS and not os.path.isabs(
        GOOGLE_APPLICATION_CREDENTIALS
    ):
        _abs_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            GOOGLE_APPLICATION_CREDENTIALS,
        )
        if os.path.exists(_abs_path):
            GOOGLE_APPLICATION_CREDENTIALS = _abs_path
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _abs_path

    # Server configuration
    # 0.0.0.0 binds all interfaces — required for cloud hosts (Render,
    # Railway) to reach the process; works fine for local dev too.
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Local fallback file database path
    LOCAL_DB_PATH: str = os.getenv("LOCAL_DB_PATH", "local_db.json")

    # CORS configuration — comma-separated list of allowed origins
    ALLOWED_ORIGINS: List[str] = [
        o.strip()
        for o in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if o.strip()
    ]

    @classmethod
    def validate_config(cls) -> None:
        """Validate critical configuration and log actionable warnings.

        Called automatically on module import so that operators see
        degradation notices in the startup log.
        """
        if not cls.GOOGLE_MAPS_API_KEY:
            logger.warning(
                "GOOGLE_MAPS_API_KEY not found in environment. "
                "The application will operate in local route simulation mode."
            )

        has_firestore_creds = (
            cls.FIREBASE_CREDENTIALS_JSON
            or cls.GOOGLE_APPLICATION_CREDENTIALS
            or cls.FIREBASE_PROJECT_ID
        )
        if not has_firestore_creds:
            logger.warning(
                "No Firebase/Firestore credentials detected. "
                "The application will operate using a local JSON database "
                "fallback."
            )
        else:
            logger.info(
                "Firestore configuration parameters loaded successfully."
            )


# Validate configuration on import
Config.validate_config()
