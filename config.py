import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploy")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    DATABASE = os.environ.get("DATABASE_PATH", str(ROOT / "instance" / "marketing.db"))
    DATASET_DIR = os.environ.get("DATASET_DIR", str(ROOT / "data"))
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    BASE_CURRENCY = os.environ.get("BASE_CURRENCY", "INR")
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes"}
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")
