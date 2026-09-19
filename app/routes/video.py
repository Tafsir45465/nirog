from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, Consultation, VideoSession
from app.security import current_user, require_appointment_access
from app.services.video import create_video_session, update_video_session_status
from app.utils.responses import ok

bp = Blueprint("video", __name__, url_prefix="/api")


def _session_or_404(session_id: int) -> VideoSession:
    session = db.session.get(VideoSession, session_id)
    if not session:
        raise AppError("Video session not found", 404, "not_found")
    return session


@bp.post("/appointments/<int:appointment_id>/video-session")
@jwt_required()
def create_session(appointment_id: int):
    user = current_user()
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        raise AppError("Appointment not found", 404, "not_found")
    require_appointment_access(user, appointment)
    consultation = Consultation.query.filter_by(appointment_id=appointment.id).first()
    if not consultation:
        raise AppError("Open the consultation before creating a video session", 409, "consultation_required")
    data = request.get_json(silent=True) or {}
    session = create_video_session(user, appointment, consultation, data.get("provider"))
    db.session.commit()
    return ok({"video_session": session.to_dict()}, "Video session ready", 201)


@bp.get("/video-sessions/<int:session_id>")
@jwt_required()
def get_session(session_id: int):
    user = current_user()
    session = _session_or_404(session_id)
    require_appointment_access(user, session.appointment)
    return ok({"video_session": session.to_dict()})


@bp.post("/video-sessions/<int:session_id>/status")
@jwt_required()
def update_session_status(session_id: int):
    user = current_user()
    session = _session_or_404(session_id)
    update_video_session_status(user, session, (request.get_json(silent=True) or {}).get("status"))
    db.session.commit()
    return ok({"video_session": session.to_dict()}, "Video session updated")
