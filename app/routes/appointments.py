from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.errors import AppError
from app.extensions import db, limiter
from app.models import Appointment, User, UserStatus
from app.security import (
    current_user,
    hospital_ids_for_user,
    require_appointment_access,
)
from app.services.audit import log_action
from app.services.appointments import cancel_appointment, create_appointment
from app.services.queues import check_in
from app.utils.responses import ok

bp = Blueprint("appointments", __name__, url_prefix="/api")


@bp.post("/appointments")
@jwt_required()
@limiter.limit("30 per hour")
def book_appointment():
    user = current_user()
    data = request.get_json(silent=True) or {}
    patient_id = data.get("patient_id")
    if user.role.value == "patient":
        patient = user.patient_profile
        if not patient:
            raise AppError("Patient profile missing", 400, "profile_missing")
        patient_id = patient.id
    if not patient_id:
        raise AppError("patient_id required", 400, "validation_error")
    appt = create_appointment(user, patient_id, data["doctor_id"], data["hospital_id"], data["scheduled_start"], data.get("appointment_type", "in_person"), data.get("reason"), data.get("department_id"))
    db.session.commit()
    return ok(appt.to_dict(), "Appointment booked", 201)


@bp.get("/appointments")
@jwt_required()
def list_appointments():
    user = current_user()
    q = Appointment.query
    if user.role.value == "patient" and user.patient_profile:
        q = q.filter(Appointment.patient_id == user.patient_profile.id)
    elif user.role.value == "doctor" and user.doctor_profile:
        q = q.filter(Appointment.doctor_id == user.doctor_profile.id)
    else:
        allowed = hospital_ids_for_user(user)
        if allowed:
            q = q.filter(Appointment.hospital_id.in_(allowed))
    patient_id = request.args.get("patient_id", type=int)
    doctor_id = request.args.get("doctor_id", type=int)
    hospital_id = request.args.get("hospital_id", type=int)
    status = request.args.get("status")
    if patient_id:
        q = q.filter(Appointment.patient_id == patient_id)
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)
    if hospital_id:
        q = q.filter(Appointment.hospital_id == hospital_id)
    if status:
        from app.models import AppointmentStatus
        if status not in {s.value for s in AppointmentStatus}:
            raise AppError("Invalid appointment status", 400, "validation_error")
        q = q.filter(Appointment.status == AppointmentStatus(status))
    appts = q.order_by(Appointment.scheduled_start.desc()).limit(100).all()
    return ok({"appointments": [a.to_dict() for a in appts]})


@bp.get("/appointments/<int:appointment_id>")
@jwt_required()
def get_appointment(appointment_id):
    user = current_user()
    appt = db.session.get(Appointment, appointment_id)
    if not appt:
        raise AppError("Appointment not found", 404, "not_found")
    require_appointment_access(user, appt)
    return ok(appt.to_dict())


@bp.post("/appointments/<int:appointment_id>/cancel")
@jwt_required()
def cancel_appointment_route(appointment_id):
    user = current_user()
    appt = db.session.get(Appointment, appointment_id)
    if not appt:
        raise AppError("Appointment not found", 404, "not_found")
    require_appointment_access(user, appt)
    data = request.get_json(silent=True) or {}
    cancel_appointment(user, appt, data.get("reason"))
    db.session.commit()
    return ok(appt.to_dict(), "Appointment cancelled")


@bp.post("/appointments/<int:appointment_id>/checkin")
@jwt_required()
def checkin_route(appointment_id):
    user = current_user()
    appt = db.session.get(Appointment, appointment_id)
    if not appt:
        raise AppError("Appointment not found", 404, "not_found")
    if user.role.value == "patient" and appt.patient_id != (user.patient_profile.id if user.patient_profile else None):
        raise AppError("Appointment access denied", 403, "appointment_access_denied")
    require_appointment_access(user, appt)
    token = check_in(user, appt)
    db.session.commit()
    return ok({"token": token.to_dict(), "appointment": appt.to_dict()}, "Checked in")