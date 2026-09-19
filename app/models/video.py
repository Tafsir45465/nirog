"""Video consultation room persistence model."""

from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models import TimestampMixin, utcnow


class VideoProvider(str):
    JITSI = "jitsi"
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"


class VideoSession(db.Model, TimestampMixin):
    __tablename__ = "video_sessions"

    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey("consultations.id"), unique=True, nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), unique=True, nullable=False, index=True)
    provider = db.Column(db.String(40), nullable=False, default=VideoProvider.JITSI)
    room_name = db.Column(db.String(180), nullable=False, unique=True)
    meeting_url = db.Column(db.String(800), nullable=False)
    provider_meeting_id = db.Column(db.String(255), nullable=True)
    host_url = db.Column(db.String(800), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="scheduled", index=True)
    scheduled_start = db.Column(db.DateTime(timezone=True), nullable=False)
    scheduled_end = db.Column(db.DateTime(timezone=True), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    consultation = db.relationship("Consultation")
    appointment = db.relationship("Appointment")
    created_by = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "consultation_id": self.consultation_id,
            "appointment_id": self.appointment_id,
            "provider": self.provider,
            "room_name": self.room_name,
            "meeting_url": self.meeting_url,
            "host_url": self.host_url,
            "status": self.status,
            "scheduled_start": self.scheduled_start.isoformat() if self.scheduled_start else None,
            "scheduled_end": self.scheduled_end.isoformat() if self.scheduled_end else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }
