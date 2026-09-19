"""Provider-neutral video room service.

Jitsi is the zero-configuration default. Zoom and Google Meet can be enabled
later by supplying provider adapter credentials; no fake provider URL is ever
returned when those credentials are missing.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

from flask import current_app

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, Consultation, User, VideoProvider, VideoSession, utcnow


def _safe_room_name(appointment_id: int) -> str:
    return f"nirog-{appointment_id}-{secrets.token_urlsafe(8).lower().replace('-', '').replace('_', '')}"


def _jitsi_url(room_name: str) -> str:
    base = current_app.config.get("JITSI_BASE_URL", "https://meet.jit.si").rstrip("/")
    return f"{base}/{room_name}"


def _provider(value: str | None) -> str:
    value = (value or current_app.config.get("VIDEO_PROVIDER", VideoProvider.JITSI)).lower().strip()
    if value not in {VideoProvider.JITSI, VideoProvider.ZOOM, VideoProvider.GOOGLE_MEET}:
        raise AppError("Unsupported video provider", 400, "invalid_video_provider")
    return value


def create_video_session(actor: User, appointment: Appointment, consultation: Consultation, provider: str | None = None) -> VideoSession:
    if appointment.appointment_type not in {"video", "telemedicine", "online"}:
        raise AppError("This appointment is not configured for video consultation", 400, "not_video_appointment")
    if actor.role.value != "doctor" or not actor.doctor_profile or actor.doctor_profile.id != appointment.doctor_id:
        raise AppError("Only the assigned doctor can create a video room", 403, "permission_denied")

    existing = VideoSession.query.filter_by(appointment_id=appointment.id).first()
    if existing:
        return existing

    selected = _provider(provider)
    room_name = _safe_room_name(appointment.id)
    if selected == VideoProvider.JITSI:
        meeting_url = _jitsi_url(room_name)
        host_url = meeting_url
    elif selected == VideoProvider.ZOOM:
        raise AppError("Zoom integration is not configured. Set ZOOM credentials before enabling it.", 503, "video_provider_unavailable")
    else:
        raise AppError("Google Meet integration is not configured. Set Google credentials before enabling it.", 503, "video_provider_unavailable")

    session = VideoSession(
        consultation_id=consultation.id,
        appointment_id=appointment.id,
        provider=selected,
        room_name=room_name,
        meeting_url=meeting_url,
        host_url=host_url,
        scheduled_start=appointment.scheduled_start,
        scheduled_end=appointment.scheduled_end,
        created_by_user_id=actor.id,
    )
    db.session.add(session)
    db.session.flush()
    return session


def update_video_session_status(actor: User, session: VideoSession, status: str) -> VideoSession:
    if actor.role.value == "doctor":
        allowed = actor.doctor_profile and actor.doctor_profile.id == session.appointment.doctor_id
    elif actor.role.value == "patient":
        allowed = actor.patient_profile and actor.patient_profile.id == session.appointment.patient_id
    else:
        allowed = False
    if not allowed:
        raise AppError("Video session access denied", 403, "permission_denied")
    if status not in {"scheduled", "active", "ended"}:
        raise AppError("Invalid video session status", 400, "validation_error")
    session.status = status
    if status == "active" and not session.started_at:
        session.started_at = utcnow()
    if status == "ended" and not session.ended_at:
        session.ended_at = utcnow()
    return session
