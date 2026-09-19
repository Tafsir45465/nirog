from __future__ import annotations

from flask import Blueprint, Response, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, Consultation, Prescription, User
from app.security import current_user, require_appointment_access
from app.services.prescriptions import create_prescription, ensure_editable, finalize_prescription, render_prescription_pdf
from app.utils.responses import ok

bp = Blueprint("prescriptions", __name__, url_prefix="/api")


@bp.post("/appointments/<int:appointment_id>/prescription")
@bp.post("/prescriptions")
@jwt_required()
def create_prescription_route(appointment_id=None):
    user = current_user()
    data = request.get_json(silent=True) or {}

    # If appointment_id from URL, use it; else from body
    if appointment_id is None:
        appointment_id = data.get("appointment_id")
        cons_id = data.get("consultation_id")
        if cons_id:
            cons = db.session.get(Consultation, cons_id)
            if not cons:
                raise AppError("Consultation not found", 404, "not_found")
            if user.role.value != "doctor" or not user.doctor_profile or cons.doctor_id != user.doctor_profile.id:
                raise AppError("Only the assigned doctor can create this prescription", 403, "permission_denied")
            prescription = create_prescription(user, cons, data)
            db.session.commit()
            return ok({"prescription": prescription.to_dict()}, "Prescription created", 201)

    appt = db.session.get(Appointment, appointment_id)
    if not appt:
        raise AppError("Appointment not found", 404, "not_found")
    require_appointment_access(user, appt)
    if user.role.value != "doctor" or not user.doctor_profile or appt.doctor_id != user.doctor_profile.id:
        raise AppError("Only the assigned doctor can create this prescription", 403, "permission_denied")
    cons = Consultation.query.filter_by(appointment_id=appt.id).first()
    if not cons:
        raise AppError("Consultation not found", 404, "not_found")
    prescription = create_prescription(user, cons, data)
    db.session.commit()
    return ok({"prescription": prescription.to_dict()}, "Prescription created", 201)


@bp.post("/prescriptions/<int:prescription_id>/finalize")
@jwt_required()
def finalize_prescription_route(prescription_id):
    user = current_user()
    prescription = db.session.get(Prescription, prescription_id)
    if not prescription:
        raise AppError("Prescription not found", 404, "not_found")
    if user.role.value != "doctor" or not user.doctor_profile or prescription.doctor_id != user.doctor_profile.id:
        raise AppError("Only the assigned doctor can finalize this prescription", 403, "permission_denied")
    ensure_editable(prescription)
    finalize_prescription(user, prescription)
    db.session.commit()
    return ok(prescription.to_dict(), "Prescription finalized")


@bp.get("/prescriptions/<int:prescription_id>/pdf")
@jwt_required()
def prescription_pdf(prescription_id):
    user = current_user()
    prescription = db.session.get(Prescription, prescription_id)
    if not prescription:
        raise AppError("Prescription not found", 404, "not_found")
    from app.security import can_access_patient
    if not can_access_patient(user, prescription.patient_id):
        raise AppError("Patient access denied", 403, "patient_access_denied")
    pdf = render_prescription_pdf(prescription)
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={prescription.prescription_code}.pdf"},
    )


@bp.get("/prescriptions")
@jwt_required()
def list_prescriptions():
    user = current_user()
    if user.role.value == "patient" and user.patient_profile:
        from app.models import Patient
        prescriptions = Prescription.query.filter_by(patient_id=user.patient_profile.id).all()
    elif user.role.value == "doctor" and user.doctor_profile:
        prescriptions = Prescription.query.filter_by(doctor_id=user.doctor_profile.id).all()
    else:
        prescriptions = Prescription.query.limit(100).all()
    return ok({"prescriptions": [p.to_dict() for p in prescriptions]})