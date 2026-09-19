"""Push notification service with Firebase Cloud Messaging integration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from flask import current_app

from app.extensions import db
from app.models import (
    DevicePlatform,
    DeviceToken,
    Notification,
    PushNotificationLog,
    User,
)
from app.services.audit import log_action

logger = logging.getLogger(__name__)


class PushNotificationProvider:
    """Base class for push notification providers."""
    provider_name = "base"

    def send(self, token: str, title: str, body: str, data: Optional[dict] = None) -> dict:
        """Send a push notification. Returns provider response."""
        raise NotImplementedError


class FirebaseProvider(PushNotificationProvider):
    """Firebase Cloud Messaging (FCM) provider."""
    provider_name = "firebase"

    def send(self, token: str, title: str, body: str, data: Optional[dict] = None) -> dict:
        """Send push notification via Firebase FCM."""
        try:
            # Try to use firebase-admin SDK
            import firebase_admin
            from firebase_admin import credentials, messaging

            # Initialize Firebase if not already initialized
            if not firebase_admin._apps:
                cred_path = current_app.config.get("FIREBASE_CREDENTIALS_PATH")
                if cred_path:
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                else:
                    # Try default credentials
                    firebase_admin.initialize_app()

            # Build the message
            notification = messaging.Notification(
                title=title,
                body=body,
            )

            android_config = messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    title=title,
                    body=body,
                    click_action="OPEN_APP",
                ),
            )

            apns_config = messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        alert=messaging.ApsAlert(
                            title=title,
                            body=body,
                        ),
                        badge=1,
                        sound="default",
                    )
                ),
            )

            web_config = messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon="/static/icons/notification.png",
                ),
            )

            message = messaging.Message(
                notification=notification,
                android=android_config,
                apns=apns_config,
                webpush=web_config,
                token=token,
                data={k: str(v) for k, v in (data or {}).items()},
            )

            # Send the message
            response = messaging.send(message)
            return {"status": "sent", "message_id": response}

        except ImportError:
            logger.warning("firebase-admin not installed, using mock FCM")
            return {"status": "mock", "message_id": f"mock_{datetime.now().timestamp()}"}
        except Exception as e:
            logger.error(f"FCM send failed: {e}")
            return {"status": "failed", "error": str(e)}


class OneSignalProvider(PushNotificationProvider):
    """OneSignal push notification provider (alternative)."""
    provider_name = "onesignal"

    def send(self, token: str, title: str, body: str, data: Optional[dict] = None) -> dict:
        """Send push notification via OneSignal."""
        try:
            import requests

            app_id = current_app.config.get("ONESIGNAL_APP_ID")
            api_key = current_app.config.get("ONESIGNAL_API_KEY")

            if not app_id or not api_key:
                return {"status": "skipped", "reason": "onesignal_not_configured"}

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Basic {api_key}",
            }

            payload = {
                "app_id": app_id,
                "include_player_ids": [token],
                "contents": {"en": body},
                "headings": {"en": title},
                "data": data or {},
            }

            response = requests.post(
                "https://onesignal.com/api/v1/notifications",
                headers=headers,
                json=payload,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                return {"status": "sent", "message_id": result.get("id")}
            else:
                return {"status": "failed", "error": response.text}

        except ImportError:
            return {"status": "skipped", "reason": "requests not installed"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


class MockProvider(PushNotificationProvider):
    """Mock provider for development/testing."""
    provider_name = "mock"

    def send(self, token: str, title: str, body: str, data: Optional[dict] = None) -> dict:
        """Log notification instead of sending."""
        logger.info(f"[MOCK PUSH] To: {token[:20]}... | Title: {title} | Body: {body[:50]}...")
        return {"status": "logged", "message_id": f"mock_{datetime.now().timestamp()}"}


def _get_provider() -> PushNotificationProvider:
    """Get the configured push notification provider."""
    provider_name = current_app.config.get("PUSH_NOTIFICATION_PROVIDER", "mock")

    if provider_name == "firebase":
        return FirebaseProvider()
    elif provider_name == "onesignal":
        return OneSignalProvider()
    else:
        return MockProvider()


# ─── Device Token Management ──────────────────────────────────────────────────


def register_device_token(
    user_id: int,
    token: str,
    platform: DevicePlatform,
    hospital_id: Optional[int] = None,
    device_name: Optional[str] = None,
    device_model: Optional[str] = None,
    app_version: Optional[str] = None,
) -> DeviceToken:
    """Register or update a device token for push notifications."""
    # Check if token already exists
    existing = DeviceToken.query.filter_by(token=token).first()

    if existing:
        # Update existing token
        existing.user_id = user_id
        existing.hospital_id = hospital_id
        existing.platform = platform
        existing.device_name = device_name or existing.device_name
        existing.device_model = device_model or existing.device_model
        existing.app_version = app_version or existing.app_version
        existing.is_active = True
        existing.last_used_at = datetime.now(timezone.utc)
        db.session.flush()
        return existing

    # Create new token
    device = DeviceToken(
        user_id=user_id,
        token=token,
        platform=platform,
        hospital_id=hospital_id,
        device_name=device_name,
        device_model=device_model,
        app_version=app_version,
        is_active=True,
        push_enabled=True,
        last_used_at=datetime.now(timezone.utc),
    )
    db.session.add(device)
    db.session.flush()

    # Audit log
    log_action(
        user=db.session.get(User, user_id),
        action="device_token_registered",
        entity="device_token",
        entity_id=device.id,
        after=device.to_dict(),
    )

    return device


def deactivate_device_token(token: str, user_id: Optional[int] = None) -> bool:
    """Deactivate a device token."""
    query = DeviceToken.query.filter_by(token=token)
    if user_id:
        query = query.filter_by(user_id=user_id)

    device = query.first()
    if not device:
        return False

    device.is_active = False
    device.deactivated_at = datetime.now(timezone.utc)
    db.session.flush()

    return True


def get_user_devices(user_id: int, hospital_id: Optional[int] = None) -> list[DeviceToken]:
    """Get all active devices for a user."""
    query = DeviceToken.query.filter_by(user_id=user_id, is_active=True)
    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)
    return query.all()


def get_hospital_devices(hospital_id: int) -> list[DeviceToken]:
    """Get all active devices for a hospital."""
    return DeviceToken.query.filter_by(hospital_id=hospital_id, is_active=True).all()


def cleanup_inactive_tokens(days_inactive: int = 90) -> int:
    """Remove device tokens that haven't been used in specified days."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_inactive)

    inactive_tokens = DeviceToken.query.filter(
        DeviceToken.last_used_at < cutoff,
        DeviceToken.is_active == True,
    ).all()

    count = 0
    for token in inactive_tokens:
        token.is_active = False
        token.deactivated_at = datetime.now(timezone.utc)
        count += 1

    db.session.flush()
    return count


# ─── Push Notification Sending ────────────────────────────────────────────────


def send_push_notification(
    user_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
    hospital_id: Optional[int] = None,
    notification_id: Optional[int] = None,
) -> list[PushNotificationLog]:
    """Send push notification to all devices of a user."""
    provider = _get_provider()
    devices = get_user_devices(user_id, hospital_id)

    if not devices:
        logger.info(f"No active devices for user {user_id}")
        return []

    logs = []
    for device in devices:
        # Skip if push is disabled
        if not device.push_enabled:
            continue

        # Check quiet hours
        if _is_quiet_hours(device):
            continue

        # Create log entry
        log = PushNotificationLog(
            device_token_id=device.id,
            notification_id=notification_id,
            title=title,
            body=body,
            data=data,
            status="pending",
        )
        db.session.add(log)
        db.session.flush()

        # Send notification
        try:
            result = provider.send(device.token, title, body, data)

            if result.get("status") in ["sent", "logged", "mock"]:
                log.status = "sent"
                log.sent_at = datetime.now(timezone.utc)
                log.provider_message_id = result.get("message_id")
                device.last_used_at = datetime.now(timezone.utc)
            else:
                log.status = "failed"
                log.error_message = result.get("error", "Unknown error")

            log.provider_response = result

        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)
            logger.error(f"Push notification failed for device {device.id}: {e}")

        db.session.flush()
        logs.append(log)

    return logs


def send_push_to_hospital(
    hospital_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
    exclude_user_id: Optional[int] = None,
) -> list[PushNotificationLog]:
    """Send push notification to all devices in a hospital."""
    provider = _get_provider()
    devices = get_hospital_devices(hospital_id)

    if not devices:
        return []

    logs = []
    for device in devices:
        # Skip excluded user
        if exclude_user_id and device.user_id == exclude_user_id:
            continue

        # Skip if push is disabled or quiet hours
        if not device.push_enabled or _is_quiet_hours(device):
            continue

        log = PushNotificationLog(
            device_token_id=device.id,
            title=title,
            body=body,
            data=data,
            status="pending",
        )
        db.session.add(log)
        db.session.flush()

        try:
            result = provider.send(device.token, title, body, data)

            if result.get("status") in ["sent", "logged", "mock"]:
                log.status = "sent"
                log.sent_at = datetime.now(timezone.utc)
                log.provider_message_id = result.get("message_id")
                device.last_used_at = datetime.now(timezone.utc)
            else:
                log.status = "failed"
                log.error_message = result.get("error", "Unknown error")

            log.provider_response = result

        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)

        db.session.flush()
        logs.append(log)

    return logs


def _is_quiet_hours(device: DeviceToken) -> bool:
    """Check if current time is within device's quiet hours."""
    if not device.quiet_hours_start or not device.quiet_hours_end:
        return False

    from zoneinfo import ZoneInfo
    tz = ZoneInfo(current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka"))
    now = datetime.now(tz).time()

    start = device.quiet_hours_start
    end = device.quiet_hours_end

    if start <= end:
        return start <= now <= end
    else:
        # Overnight quiet hours (e.g., 22:00 - 07:00)
        return now >= start or now <= end


# ─── Notification Preferences ─────────────────────────────────────────────────


def update_push_preferences(
    user_id: int,
    device_token_id: int,
    push_enabled: Optional[bool] = None,
    quiet_hours_start: Optional[str] = None,
    quiet_hours_end: Optional[str] = None,
) -> DeviceToken:
    """Update push notification preferences for a device."""
    device = DeviceToken.query.filter_by(id=device_token_id, user_id=user_id).first()
    if not device:
        raise ValueError("Device not found")

    if push_enabled is not None:
        device.push_enabled = push_enabled

    if quiet_hours_start is not None:
        from datetime import time as dt_time
        h, m = map(int, quiet_hours_start.split(":"))
        device.quiet_hours_start = dt_time(h, m)

    if quiet_hours_end is not None:
        from datetime import time as dt_time
        h, m = map(int, quiet_hours_end.split(":"))
        device.quiet_hours_end = dt_time(h, m)

    db.session.flush()
    return device


def get_push_stats(hospital_id: Optional[int] = None) -> dict:
    """Get push notification statistics."""
    from sqlalchemy import func

    query = PushNotificationLog.query
    if hospital_id:
        query = query.join(DeviceToken).filter(DeviceToken.hospital_id == hospital_id)

    total = query.count()
    sent = query.filter_by(status="sent").count()
    failed = query.filter_by(status="failed").count()
    delivered = query.filter_by(status="delivered").count()

    # Active devices
    device_query = DeviceToken.query.filter_by(is_active=True)
    if hospital_id:
        device_query = device_query.filter_by(hospital_id=hospital_id)

    active_devices = device_query.count()

    return {
        "total_notifications": total,
        "sent": sent,
        "delivered": delivered,
        "failed": failed,
        "active_devices": active_devices,
        "success_rate": round((sent / total * 100), 2) if total > 0 else 0,
    }
