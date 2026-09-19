from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Patient, User
from app.security import current_user
from app.utils.responses import ok

bp = Blueprint("patients", __name__, url_prefix="/api/patient")


@bp.post("/profile")
@jwt_required()
def update_profile():
    user = current_user()
    if not user.patient_profile:
        raise AppError("Patient profile not found", 404, "not_found")

    data = request.get_json(silent=True) or {}
    patient = user.patient_profile

    # Update fields
    for field in ("date_of_birth", "gender", "address", "emergency_contact_name", "emergency_contact_phone", "blood_group", "basic_health_info"):
        if data.get(field) is not None:
            # Need to handle date conversion if necessary for DOB
            if field == "date_of_birth":
                from datetime import date
                setattr(patient, field, date.fromisoformat(data[field]))
            else:
                setattr(patient, field, data[field])

    db.session.commit()
    return ok(patient.to_dict(), "Profile updated")
