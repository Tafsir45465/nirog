from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, AppointmentStatus, Consultation, User, utcnow
from app.security import current_user, require_appointment_access
from app.services.audit import log_action
from app.services.notifications import notify
from app.utils.responses import ok

bp = Blueprint("consultations", __name__, url_prefix="/api")


@bp.post("/appointments/<int:appointment_id>/consultation")
@bp.post("/consultations")
@jwt_required()
def start_consultation(appointment_id=None):
    user = current_user()
    data = request.get_json(silent=True) or {}

    # If appointment_id from URL, use it; else from body
    if appointment_id is None:
        appointment_id = data.get("appointment_id")

    appt = db.session.get(Appointment, appointment_id)
    if not appt:
        raise AppError("Appointment not found", 404, "not_found")
    require_appointment_access(user, appt)
    if user.role.value != "doctor":
        raise AppError("Only the assigned doctor can record a consultation", 403, "permission_denied")
    cons = Consultation.query.filter_by(appointment_id=appt.id).first()
    if not cons:
        cons = Consultation(appointment_id=appt.id, patient_id=appt.patient_id, doctor_id=appt.doctor_id, hospital_id=appt.hospital_id, symptoms=data.get("symptoms"), observations=data.get("observations"), notes=data.get("notes"))
        db.session.add(cons)
        db.session.flush()
    else:
        for field in ("symptoms", "observations", "notes"):
            if data.get(field) is not None:
                setattr(cons, field, data[field])
    appt.status = "in_consultation"
    log_action(user, "consultation.opened", "Consultation", cons.id, after=cons.to_dict() if hasattr(cons, "to_dict") else None)
    db.session.commit()
    return ok({"consultation": {"id": cons.id, "appointment_id": cons.appointment_id, "patient_id": cons.patient_id, "doctor_id": cons.doctor_id, "hospital_id": cons.hospital_id, "symptoms": cons.symptoms, "observations": cons.observations, "notes": cons.notes}}, "Consultation opened", 201)


@bp.post("/consultations/<int:consultation_id>/complete")
@jwt_required()
def complete_consultation(consultation_id):
    user = current_user()
    cons = db.session.get(Consultation, consultation_id)
    if not cons:
        raise AppError("Consultation not found", 404, "not_found")
    if user.role.value != "doctor" or not user.doctor_profile or cons.doctor_id != user.doctor_profile.id:
        raise AppError("Only the assigned doctor can complete this consultation", 403, "permission_denied")
    if cons.completed_at is not None:
        raise AppError("Consultation is already completed", 409, "already_completed")
    data = request.get_json(silent=True) or {}
    for field in ("symptoms", "observations", "notes", "advice"):
        if data.get(field) is not None:
            setattr(cons, field, data[field])
    if data.get("follow_up_date"):
        from datetime import date
        cons.follow_up_date = date.fromisoformat(data["follow_up_date"])
    cons.completed_at = utcnow()
    cons.appointment.status = AppointmentStatus.COMPLETED
    notify(
        cons.patient.user_id,
        "consultation_completed",
        "Consultation completed",
        f"Your consultation with {cons.doctor.user.full_name} has been completed.",
        {"consultation_id": cons.id},
    )
    log_action(user, "consultation.completed", "Consultation", cons.id)
    db.session.commit()
    return ok({"id": cons.id, "follow_up_date": cons.follow_up_date.isoformat() if cons.follow_up_date else None}, "Consultation completed")