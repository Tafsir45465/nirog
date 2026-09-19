"""Environment-driven configuration for Nirog."""

from __future__ import annotations

import os
from datetime import timedelta


class BaseConfig:
    # Development defaults keep local setup convenient; ProductionConfig rejects them.
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///nirog.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "60")))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "14")))
    BUSINESS_TIMEZONE = os.getenv("BUSINESS_TIMEZONE", "Asia/Dhaka")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    JSON_SORT_KEYS = False
    TESTING = False
    VIDEO_PROVIDER = os.getenv("VIDEO_PROVIDER", "jitsi")
    JITSI_BASE_URL = os.getenv("JITSI_BASE_URL", "https://meet.jit.si")
    # Leave third-party providers disabled until credentials are configured.
    ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "")
    ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
    ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
    GOOGLE_MEET_CREDENTIALS_FILE = os.getenv("GOOGLE_MEET_CREDENTIALS_FILE", "")
    NOTIFICATION_CHANNELS = os.getenv("NOTIFICATION_CHANNELS", "in_app,email,sms")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMS_PROVIDER = os.getenv("SMS_PROVIDER", "log")
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
    # Backup configuration
    BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads"))
    BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    # Push notification configuration
    PUSH_NOTIFICATION_PROVIDER = os.getenv("PUSH_NOTIFICATION_PROVIDER", "mock")  # mock, firebase, onesignal
    FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "")
    ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "")
    ONESIGNAL_API_KEY = os.getenv("ONESIGNAL_API_KEY", "")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)


class ProductionConfig(BaseConfig):
    DEBUG = False


_CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None):
    config_name = name or os.getenv("FLASK_ENV", "development")
    config = _CONFIGS.get(config_name, DevelopmentConfig)
    if config_name == "production":
        secret = os.getenv("SECRET_KEY", "")
        jwt_secret = os.getenv("JWT_SECRET_KEY", "")
        if not secret or secret == "dev-only-change-me":
            raise RuntimeError("SECRET_KEY must be set to a strong value in production")
        if not jwt_secret or jwt_secret == "dev-only-change-me":
            raise RuntimeError("JWT_SECRET_KEY must be set to a strong value in production")
    return config
