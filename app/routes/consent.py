"""Patient consent management routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import (
    ConsentStatus,
    ConsentType,
    Patient,
    PatientConsent,
    Role,
)
from app.security import current_user, require_patient_access, roles_required
from app.services.consent import (
    check_consent_status,
    create_consent_request,
    deny_consent,
    get_hospital_consents,
    get_patient_consents,
    grant_consent,
    revoke_consent,
    require_consent_for_appointment,
)
from app.utils.responses import ok, error

bp = Blueprint("consent", __name__, url_prefix="/api/consents")


# ─── Patient Endpoints ────────────────────────────────────────────────────────


@bp.get("/my")
@jwt_required()
def list_my_consents():
    """List current patient's consents."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can view their consents", 403, "permission_denied")

    consent_type = request.args.get("consent_type")
    status = request.args.get("status")

    ct = ConsentType(consent_type) if consent_type else None
    cs = ConsentStatus(status) if status else None

    consents = get_patient_consents(
        patient_id=user.patient_profile.id,
        consent_type=ct,
        status=cs,
    )

    return ok(
        data=[c.to_dict() for c in consents],
        meta={"total": len(consents)},
    )


@bp.get("/my/<int:consent_id>")
@jwt_required()
def get_my_consent(consent_id: int):
    """Get a specific consent record for the current patient."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can view their consents", 403, "permission_denied")

    consent = db.session.get(PatientConsent, consent_id)
    if not consent:
        raise AppError("Consent not found", 404, "not_found")

    if consent.patient_id != user.patient_profile.id:
        raise AppError("Access denied", 403, "access_denied")

    return ok(data=consent.to_dict())


@bp.post("/my/grant/<int:consent_id>")
@jwt_required()
def grant_my_consent(consent_id: int):
    """Patient grants consent."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can grant consent", 403, "permission_denied")

    data = request.get_json(silent=True) or {}

    try:
        consent = grant_consent(
            consent_id=consent_id,
            patient=user.patient_profile,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            signature_data=data.get("signature_data"),
            notes=data.get("notes"),
        )
        db.session.commit()
        return ok(data=consent.to_dict(), message="Consent granted successfully")
    except ValueError as e:
        raise AppError(str(e), 400, "invalid_consent_action")
    except PermissionError as e:
        raise AppError(str(e), 403, "permission_denied")


@bp.post("/my/deny/<int:consent_id>")
@jwt_required()
def deny_my_consent(consent_id: int):
    """Patient denies consent."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can deny consent", 403, "permission_denied")

    data = request.get_json(silent=True) or {}

    try:
        consent = deny_consent(
            consent_id=consent_id,
            patient=user.patient_profile,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            notes=data.get("notes"),
        )
        db.session.commit()
        return ok(data=consent.to_dict(), message="Consent denied")
    except ValueError as e:
        raise AppError(str(e), 400, "invalid_consent_action")
    except PermissionError as e:
        raise AppError(str(e), 403, "permission_denied")


@bp.post("/my/revoke/<int:consent_id>")
@jwt_required()
def revoke_my_consent(consent_id: int):
    """Patient revokes previously granted consent."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can revoke consent", 403, "permission_denied")

    data = request.get_json(silent=True) or {}

    try:
        consent = revoke_consent(
            consent_id=consent_id,
            patient=user.patient_profile,
            reason=data.get("reason"),
        )
        db.session.commit()
        return ok(data=consent.to_dict(), message="Consent revoked successfully")
    except ValueError as e:
        raise AppError(str(e), 400, "invalid_consent_action")
    except PermissionError as e:
        raise AppError(str(e), 403, "permission_denied")


@bp.get("/my/check/<consent_type>")
@jwt_required()
def check_my_consent_status(consent_type: str):
    """Check if current patient has valid consent for a specific type."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can check their consent", 403, "permission_denied")

    try:
        ct = ConsentType(consent_type)
    except ValueError:
        raise AppError(
            f"Invalid consent type. Valid types: {[t.value for t in ConsentType]}",
            400,
            "invalid_consent_type",
        )

    # Get hospital_id from query param or header
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        hospital_id = request.headers.get("X-Hospital-Id", type=int)

    if not hospital_id:
        raise AppError("hospital_id is required", 400, "hospital_required")

    result = check_consent_status(
        patient_id=user.patient_profile.id,
        hospital_id=hospital_id,
        consent_type=ct,
    )

    return ok(data=result)


# ─── Admin/Hospital Endpoints ─────────────────────────────────────────────────


@bp.post("/create")
@jwt_required()
@roles_required(Role.ADMIN, Role.RECEPTIONIST, Role.DOCTOR)
def create_consent():
    """Create a consent request for a patient (admin/receptionist/doctor)."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    patient_id = data.get("patient_id")
    hospital_id = data.get("hospital_id")
    consent_type = data.get("consent_type")

    if not patient_id or not hospital_id or not consent_type:
        raise AppError(
            "patient_id, hospital_id, and consent_type are required",
            400,
            "missing_fields",
        )

    try:
        ct = ConsentType(consent_type)
    except ValueError:
        raise AppError(
            f"Invalid consent type. Valid types: {[t.value for t in ConsentType]}",
            400,
            "invalid_consent_type",
        )

    # Verify patient exists
    patient = db.session.get(Patient, patient_id)
    if not patient:
        raise AppError("Patient not found", 404, "patient_not_found")

    try:
        consent = create_consent_request(
            patient_id=patient_id,
            hospital_id=hospital_id,
            consent_type=ct,
            title=data.get("title"),
            description=data.get("description"),
            version=data.get("version", "1.0"),
            expires_in_days=data.get("expires_in_days"),
            created_by=user,
        )
        db.session.commit()
        return ok(data=consent.to_dict(), message="Consent request created"), 201
    except Exception as e:
        db.session.rollback()
        raise AppError(f"Failed to create consent: {str(e)}", 500, "create_failed")


@bp.get("/patient/<int:patient_id>")
@jwt_required()
@roles_required(Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST, Role.SUPER_ADMIN)
def get_patient_consents_endpoint(patient_id: int):
    """Get all consents for a specific patient (admin/doctor/receptionist view)."""
    user = current_user()

    from app.security import can_access_patient
    if not can_access_patient(user, patient_id):
        raise AppError("Access denied", 403, "access_denied")

    consent_type = request.args.get("consent_type")
    status = request.args.get("status")
    hospital_id = request.args.get("hospital_id", type=int)

    ct = ConsentType(consent_type) if consent_type else None
    cs = ConsentStatus(status) if status else None

    consents = get_patient_consents(
        patient_id=patient_id,
        hospital_id=hospital_id,
        consent_type=ct,
        status=cs,
    )

    return ok(
        data=[c.to_dict() for c in consents],
        meta={"total": len(consents)},
    )


@bp.get("/hospital/<int:hospital_id>")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def get_hospital_consents_endpoint(hospital_id: int):
    """Get all consents for a hospital (admin view)."""
    from app.security import require_hospital_access
    require_hospital_access(current_user(), hospital_id)

    consent_type = request.args.get("consent_type")
    status = request.args.get("status")

    ct = ConsentType(consent_type) if consent_type else None
    cs = ConsentStatus(status) if status else None

    consents = get_hospital_consents(
        hospital_id=hospital_id,
        consent_type=ct,
        status=cs,
    )

    # Calculate stats
    total = len(consents)
    granted = sum(1 for c in consents if c.status == ConsentStatus.GRANTED)
    pending = sum(1 for c in consents if c.status == ConsentStatus.PENDING)
    denied = sum(1 for c in consents if c.status == ConsentStatus.DENIED)
    revoked = sum(1 for c in consents if c.status == ConsentStatus.REVOKED)

    return ok(
        data=[c.to_dict() for c in consents],
        meta={
            "total": total,
            "granted": granted,
            "pending": pending,
            "denied": denied,
            "revoked": revoked,
        },
    )


@bp.get("/check/<int:patient_id>/<consent_type>")
@jwt_required()
@roles_required(Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST, Role.SUPER_ADMIN)
def check_patient_consent(patient_id: int, consent_type: str):
    """Check if a patient has valid consent (used before appointments)."""
    user = current_user()

    from app.security import can_access_patient
    if not can_access_patient(user, patient_id):
        raise AppError("Access denied", 403, "access_denied")

    try:
        ct = ConsentType(consent_type)
    except ValueError:
        raise AppError(
            f"Invalid consent type. Valid types: {[t.value for t in ConsentType]}",
            400,
            "invalid_consent_type",
        )

    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        hospital_id = request.headers.get("X-Hospital-Id", type=int)

    if not hospital_id:
        raise AppError("hospital_id is required", 400, "hospital_required")

    result = check_consent_status(
        patient_id=patient_id,
        hospital_id=hospital_id,
        consent_type=ct,
    )

    return ok(data=result)


# ─── Pre-appointment Consent Check ────────────────────────────────────────────


@bp.post("/verify-for-appointment")
@jwt_required()
@roles_required(Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST)
def verify_consent_for_appointment():
    """Verify patient has required consent before booking an appointment."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    patient_id = data.get("patient_id")
    hospital_id = data.get("hospital_id")
    consent_type = data.get("consent_type", "treatment")

    if not patient_id or not hospital_id:
        raise AppError("patient_id and hospital_id are required", 400, "missing_fields")

    try:
        ct = ConsentType(consent_type)
    except ValueError:
        raise AppError(
            f"Invalid consent type. Valid types: {[t.value for t in ConsentType]}",
            400,
            "invalid_consent_type",
        )

    try:
        consent = require_consent_for_appointment(patient_id, hospital_id, ct)
        return ok(
            data={
                "consent_id": consent.id,
                "consent_type": consent.consent_type.value,
                "granted_at": consent.granted_at.isoformat() if consent.granted_at else None,
            },
            message="Consent verified for appointment",
        )
    except ValueError as e:
        return error(message=str(e), code="consent_required"), 403
