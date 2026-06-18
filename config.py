import os
import logging
from typing import Optional

# Setup standard logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("CarbonPlatformConfig")

def load_dotenv() -> None:
    """Robust custom .env loader that parses key=value and key:value formats."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
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
                        # Strip quotes if present
                        if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                            val = val[1:-1]
                        if key:
                            os.environ[key] = val
            logger.info("Configurations loaded from .env file successfully.")
        except Exception as e:
            logger.warning(f"Failed to load .env file: {str(e)}")

# Load .env variables on start
load_dotenv()


class Config:
    """Secure Environment Configuration Manager."""
    
    ENV: str = os.getenv("ENV", "development").lower()
    
    # Google Routes API Key — must come from environment only. Never hardcode a
    # real key here as a "default": this file is tracked by git, so a literal
    # key string here gets committed permanently. If unset, RoutesServiceClient
    # already degrades gracefully to its own simulated_fallback mode.
    GOOGLE_MAPS_API_KEY: Optional[str] = os.getenv("GOOGLE_MAPS_API_KEY")
    
    # Firebase / Firestore Configurations
    FIREBASE_PROJECT_ID: Optional[str] = os.getenv("FIREBASE_PROJECT_ID")
    FIREBASE_CREDENTIALS_JSON: Optional[str] = os.getenv("FIREBASE_CREDENTIALS_JSON")
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "service-account.json"
    
    # Resolve relative credentials file paths to absolute path so Google library finds it
    if GOOGLE_APPLICATION_CREDENTIALS and not os.path.isabs(GOOGLE_APPLICATION_CREDENTIALS):
        _abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), GOOGLE_APPLICATION_CREDENTIALS)
        if os.path.exists(_abs_path):
            GOOGLE_APPLICATION_CREDENTIALS = _abs_path
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _abs_path

    # Server configuration
    # 0.0.0.0 (not 127.0.0.1): binds all interfaces. Required for Render/Railway/any
    # cloud host to reach this process at all; still works fine for local dev too.
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Local fallback file database path
    LOCAL_DB_PATH: str = os.getenv("LOCAL_DB_PATH", "local_db.json")

    @classmethod
    def validate_config(cls) -> None:
        """Validate if required API keys are available, logging warnings for fallbacks."""
        if not cls.GOOGLE_MAPS_API_KEY:
            logger.warning(
                "GOOGLE_MAPS_API_KEY not found in environment. "
                "The application will operate in local route simulation mode."
            )
        
        has_firestore_creds = (
            cls.FIREBASE_CREDENTIALS_JSON or 
            cls.GOOGLE_APPLICATION_CREDENTIALS or 
            cls.FIREBASE_PROJECT_ID
        )
        if not has_firestore_creds:
            logger.warning(
                "No Firebase/Firestore credentials detected. "
                "The application will operate using a local JSON database fallback."
            )
        else:
            logger.info("Firestore configuration parameters loaded successfully.")

# Validate configuration on import
Config.validate_config()
