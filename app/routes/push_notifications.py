"""Push notification management routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import DevicePlatform, DeviceToken, Role
from app.security import current_user, require_hospital_access, roles_required
from app.services.push_notifications import (
    deactivate_device_token,
    get_push_stats,
    get_user_devices,
    register_device_token,
    send_push_notification,
    send_push_to_hospital,
    update_push_preferences,
    cleanup_inactive_tokens,
)
from app.utils.responses import ok, error

bp = Blueprint("push_notifications", __name__, url_prefix="/api/push")


# ─── Device Registration ──────────────────────────────────────────────────────


@bp.post("/register")
@jwt_required()
def register_device():
    """Register a device token for push notifications."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    token = data.get("token")
    platform = data.get("platform")

    if not token or not platform:
        raise AppError("token and platform are required", 400, "missing_fields")

    try:
        plat = DevicePlatform(platform)
    except ValueError:
        raise AppError(
            f"Invalid platform. Valid platforms: {[p.value for p in DevicePlatform]}",
            400,
            "invalid_platform",
        )

    hospital_id = data.get("hospital_id")
    if not hospital_id:
        hospital_id = request.headers.get("X-Hospital-Id", type=int)

    device = register_device_token(
        user_id=user.id,
        token=token,
        platform=plat,
        hospital_id=hospital_id,
        device_name=data.get("device_name"),
        device_model=data.get("device_model"),
        app_version=data.get("app_version"),
    )
    db.session.commit()

    return ok(data=device.to_dict(), message="Device registered successfully")


@bp.post("/unregister")
@jwt_required()
def unregister_device():
    """Unregister a device token."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    token = data.get("token")
    if not token:
        raise AppError("token is required", 400, "missing_fields")

    success = deactivate_device_token(token, user.id)
    db.session.commit()

    if success:
        return ok(message="Device unregistered successfully")
    else:
        return error(message="Device not found", code="not_found"), 404


@bp.get("/devices")
@jwt_required()
def list_my_devices():
    """List current user's registered devices."""
    user = current_user()

    hospital_id = request.args.get("hospital_id", type=int)
    devices = get_user_devices(user.id, hospital_id)

    return ok(
        data=[d.to_dict() for d in devices],
        meta={"total": len(devices)},
    )


# ─── Notification Preferences ─────────────────────────────────────────────────


@bp.put("/preferences/<int:device_id>")
@jwt_required()
def update_preferences(device_id: int):
    """Update push notification preferences for a device."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    try:
        device = update_push_preferences(
            user_id=user.id,
            device_token_id=device_id,
            push_enabled=data.get("push_enabled"),
            quiet_hours_start=data.get("quiet_hours_start"),
            quiet_hours_end=data.get("quiet_hours_end"),
        )
        db.session.commit()
        return ok(data=device.to_dict(), message="Preferences updated")
    except ValueError as e:
        raise AppError(str(e), 404, "device_not_found")


# ─── Send Push Notifications (Admin/Doctor) ───────────────────────────────────


@bp.post("/send")
@jwt_required()
@roles_required(Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST, Role.SUPER_ADMIN)
def send_push():
    """Send push notification to a specific user."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    target_user_id = data.get("user_id")
    title = data.get("title")
    body = data.get("body")

    if not target_user_id or not title or not body:
        raise AppError("user_id, title, and body are required", 400, "missing_fields")

    hospital_id = data.get("hospital_id")
    if not hospital_id:
        hospital_id = request.headers.get("X-Hospital-Id", type=int)

    logs = send_push_notification(
        user_id=target_user_id,
        title=title,
        body=body,
        data=data.get("data"),
        hospital_id=hospital_id,
    )
    db.session.commit()

    return ok(
        data={
            "sent_count": len([l for l in logs if l.status == "sent"]),
            "failed_count": len([l for l in logs if l.status == "failed"]),
            "logs": [l.to_dict() for l in logs],
        },
        message="Push notifications sent",
    )


@bp.post("/send-hospital")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def send_hospital_push():
    """Send push notification to all devices in a hospital."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    hospital_id = data.get("hospital_id")
    title = data.get("title")
    body = data.get("body")

    if not hospital_id or not title or not body:
        raise AppError("hospital_id, title, and body are required", 400, "missing_fields")

    require_hospital_access(user, hospital_id)

    logs = send_push_to_hospital(
        hospital_id=hospital_id,
        title=title,
        body=body,
        data=data.get("data"),
        exclude_user_id=user.id,
    )
    db.session.commit()

    return ok(
        data={
            "sent_count": len([l for l in logs if l.status == "sent"]),
            "failed_count": len([l for l in logs if l.status == "failed"]),
        },
        message="Hospital push notifications sent",
    )


# ─── Statistics ───────────────────────────────────────────────────────────────


@bp.get("/stats")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def stats():
    """Get push notification statistics."""
    hospital_id = request.args.get("hospital_id", type=int)
    if hospital_id:
        require_hospital_access(current_user(), hospital_id)

    stats = get_push_stats(hospital_id)
    return ok(data=stats)


# ─── Cleanup ──────────────────────────────────────────────────────────────────


@bp.post("/cleanup")
@jwt_required()
@roles_required(Role.SUPER_ADMIN)
def cleanup():
    """Cleanup inactive device tokens."""
    data = request.get_json(silent=True) or {}
    days_inactive = data.get("days_inactive", 90)

    count = cleanup_inactive_tokens(days_inactive)
    db.session.commit()

    return ok(
        data={"deactivated_count": count},
        message=f"Deactivated {count} inactive device tokens",
    )
