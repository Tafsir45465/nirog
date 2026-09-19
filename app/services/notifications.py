from __future__ import annotations

import base64
import json
import smtplib
from email.message import EmailMessage
from urllib import request as urlrequest

from flask import current_app

from app.extensions import db
from app.models import Notification, User


class NotificationProvider:
    channel = "base"

    def send(self, notification: Notification, user: User) -> dict:
        raise NotImplementedError


class InAppNotificationProvider(NotificationProvider):
    channel = "in_app"

    def send(self, notification: Notification, user: User) -> dict:
        db.session.add(notification)
        return {"channel": self.channel, "status": "queued"}


class EmailNotificationProvider(NotificationProvider):
    channel = "email"

    def send(self, notification: Notification, user: User) -> dict:
        if not user.email:
            return {"channel": self.channel, "status": "skipped", "reason": "missing_email"}
        host = current_app.config.get("SMTP_HOST")
        if not host:
            current_app.logger.info("EMAIL[%s] %s: %s", user.email, notification.title, notification.body)
            return {"channel": self.channel, "status": "logged"}

        msg = EmailMessage()
        msg["Subject"] = notification.title
        msg["From"] = current_app.config.get("SMTP_FROM_EMAIL") or current_app.config.get("SMTP_USERNAME") or "noreply@nirog.local"
        msg["To"] = user.email
        msg.set_content(notification.body)

        port = int(current_app.config.get("SMTP_PORT") or 587)
        username = current_app.config.get("SMTP_USERNAME")
        password = current_app.config.get("SMTP_PASSWORD")
        use_tls = current_app.config.get("SMTP_USE_TLS", True)
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
        return {"channel": self.channel, "status": "sent"}


class SmsNotificationProvider(NotificationProvider):
    channel = "sms"

    def send(self, notification: Notification, user: User) -> dict:
        if not user.phone:
            return {"channel": self.channel, "status": "skipped", "reason": "missing_phone"}
        provider = (current_app.config.get("SMS_PROVIDER") or "log").lower()
        body = notification.body[:320]
        if provider != "twilio":
            current_app.logger.info("SMS[%s] %s", user.phone, body)
            return {"channel": self.channel, "status": "logged"}

        sid = current_app.config.get("TWILIO_ACCOUNT_SID")
        token = current_app.config.get("TWILIO_AUTH_TOKEN")
        from_number = current_app.config.get("TWILIO_FROM_NUMBER")
        if not (sid and token and from_number):
            return {"channel": self.channel, "status": "skipped", "reason": "twilio_not_configured"}

        payload = f"To={user.phone}&From={from_number}&Body={body}".encode("utf-8")
        req = urlrequest.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=payload)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        basic = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req.add_header("Authorization", f"Basic {basic}")
        with urlrequest.urlopen(req, timeout=10) as resp:
            return {"channel": self.channel, "status": "sent", "provider_status": resp.status}


def _enabled_channels(channels: list[str] | tuple[str, ...] | None = None) -> list[str]:
    if channels:
        return list(channels)
    raw = current_app.config.get("NOTIFICATION_CHANNELS", "in_app,email,sms")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _providers_for(channels: list[str]) -> list[NotificationProvider]:
    providers: list[NotificationProvider] = []
    for channel in channels:
        if channel == "in_app":
            providers.append(InAppNotificationProvider())
        elif channel == "email":
            providers.append(EmailNotificationProvider())
        elif channel == "sms":
            providers.append(SmsNotificationProvider())
        elif channel == "push":
            providers.append(PushNotificationProvider())
    return providers


class PushNotificationProvider(NotificationProvider):
    """Push notification provider that sends via Firebase/OneSignal."""
    channel = "push"

    def send(self, notification: Notification, user: User) -> dict:
        try:
            from app.services.push_notifications import send_push_notification
            from app.extensions import db

            logs = send_push_notification(
                user_id=user.id,
                title=notification.title,
                body=notification.body,
                data=notification.data,
                notification_id=notification.id,
            )
            db.session.commit()
            return {"channel": self.channel, "status": "sent", "devices_notified": len(logs)}
        except Exception as e:
            current_app.logger.exception("Push notification provider failed")
            return {"channel": self.channel, "status": "failed", "error": str(e)}


def notify(user_id: int, event_type: str, title: str, body: str, data=None, channels=None):
    """Create an in-app notification and optionally fan it out to email/SMS.

    Development is safe by default: without SMTP/Twilio credentials, email and SMS
    are written to the app log instead of being sent to real users.
    """
    user = db.session.get(User, user_id)
    if not user:
        return None

    notification = Notification(user_id=user_id, event_type=event_type, title=title, body=body, data=data or {})
    delivery_results = []
    for provider in _providers_for(_enabled_channels(channels)):
        try:
            delivery_results.append(provider.send(notification, user))
        except Exception as exc:  # keep clinical workflows from failing because an SMS gateway is down
            current_app.logger.exception("Notification provider failed: %s", provider.channel)
            delivery_results.append({"channel": provider.channel, "status": "failed", "error": str(exc)})

    notification.data = {**(notification.data or {}), "delivery": delivery_results}
    return notification


def notify_appointment_booked(appointment):
    when = appointment.scheduled_start.strftime("%d %b %Y, %I:%M %p")
    notify(
        appointment.patient.user_id,
        "appointment_booked",
        "Appointment booked",
        f"Your appointment with {appointment.doctor.user.full_name} at {appointment.hospital.name} is booked for {when}.",
        {"appointment_id": appointment.id},
    )
    notify(
        appointment.doctor.user_id,
        "doctor_appointment_booked",
        "New appointment booked",
        f"{appointment.patient.user.full_name} booked an appointment for {when}.",
        {"appointment_id": appointment.id},
    )


def notify_appointment_cancelled(appointment):
    notify(
        appointment.patient.user_id,
        "appointment_cancelled",
        "Appointment cancelled",
        f"Your appointment with {appointment.doctor.user.full_name} has been cancelled.",
        {"appointment_id": appointment.id, "reason": appointment.cancellation_reason},
    )
    notify(
        appointment.doctor.user_id,
        "doctor_appointment_cancelled",
        "Appointment cancelled",
        f"Appointment for {appointment.patient.user.full_name} has been cancelled.",
        {"appointment_id": appointment.id, "reason": appointment.cancellation_reason},
    )
