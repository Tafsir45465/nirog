"""QR code patient identification routes."""

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Patient, Role
from app.security import current_user, require_hospital_access, roles_required
from app.services.qr_service import (
    generate_patient_qr_code,
    get_patient_qr_code,
    cleanup_old_qr_codes,
)
from app.utils.responses import ok, error

bp = Blueprint("qr", __name__, url_prefix="/api/qr")

# QR files contain patient identifiers and must not be served without auth.
_QR_FILE_ROLES = {Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST, Role.DOCTOR, Role.PATIENT}


@bp.post("/generate/<int:patient_id>")
@jwt_required()
def generate_qr(patient_id: int):
    """Generate a QR code for patient identification."""
    user = current_user()
    
    # Verify patient access
    from app.security import can_access_patient
    if not can_access_patient(user, patient_id):
        raise AppError("Access denied", 403, "access_denied")
    
    hospital_id = request.args.get("hospital_id", type=int)
    
    try:
        result = generate_patient_qr_code(patient_id, hospital_id)
        db.session.commit()
        return ok(data=result, message="QR code generated successfully")
    except ValueError as e:
        raise AppError(str(e), 404, "patient_not_found")


@bp.get("/<int:patient_id>")
@jwt_required()
def get_qr(patient_id: int):
    """Get QR code for a patient."""
    from app.security import can_access_patient
    if not can_access_patient(current_user(), patient_id):
        raise AppError("Access denied", 403, "access_denied")
    
    result = get_patient_qr_code(patient_id)
    if not result:
        raise AppError("QR code not found for this patient", 404, "not_found")
    
    return ok(data=result)


@bp.get("/file/<filename>")
@jwt_required()
@roles_required(*_QR_FILE_ROLES)
def qr_file(filename: str):
    """Serve QR code file (requires authentication)."""
    try:
        return get_qr_code_file(filename)
    except Exception as e:
        raise AppError(f"QR code file not found: {str(e)}", 404, "not_found")


@bp.post("/cleanup")
@jwt_required()
@roles_required(Role.SUPER_ADMIN)
def cleanup_qr():
    """Clean up old QR codes."""
    data = request.get_json(silent=True) or {}
    days = data.get("days", 365)
    
    count = cleanup_old_qr_codes(days)
    db.session.commit()
    
    return ok(data={"deleted_count": count}, message=f"Deleted {count} old QR codes")


@bp.get("/sample")
def sample_qr():
    """Show sample QR code structure."""
    return ok(
        data={
            "format": "patient_id:hospital_id:timestamp",
            "example": "123:1:AUG%2017%202026%2014%3A30%3A00+00%3A00",
            "purpose": "Patient identification at reception",
            "scannable": "Yes",
        }
    )