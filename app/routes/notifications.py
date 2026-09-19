from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.extensions import db
from app.models import Notification
from app.security import current_user
from app.utils.responses import ok

bp = Blueprint("notifications", __name__, url_prefix="/api")


@bp.get("/notifications")
@jwt_required()
def list_notifications():
    user = current_user()
    unread_only = request.args.get("unread", "false").lower() == "true"
    q = Notification.query.filter_by(user_id=user.id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    notifs = q.order_by(Notification.created_at.desc()).limit(100).all()
    return ok({"notifications": [{"id": n.id, "event_type": n.event_type, "title": n.title, "body": n.body, "read_at": n.read_at.isoformat() if n.read_at else None, "created_at": n.created_at.isoformat()} for n in notifs]})


@bp.post("/notifications/<int:notification_id>/read")
@jwt_required()
def mark_read(notification_id):
    user = current_user()
    notif = db.session.get(Notification, notification_id)
    if not notif or notif.user_id != user.id:
        from app.errors import AppError
        raise AppError("Notification not found", 404, "not_found")
    from datetime import datetime, timezone
    notif.read_at = datetime.now(timezone.utc)
    db.session.commit()
    return ok(None, "Marked as read")