from __future__ import annotations

from flask import request

from app.extensions import db
from app.models import AuditLog, User


def log_action(user: User | None, action: str, entity: str, entity_id=None, before=None, after=None):
    log = AuditLog(
        user_id=user.id if user else None,
        role=user.role.value if user else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr) if request else None,
        user_agent=request.headers.get("User-Agent") if request else None,
        before=before,
        after=after,
    )
    db.session.add(log)
    return log
