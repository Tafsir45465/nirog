from app.extensions import db
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)
