from __future__ import annotations

from functools import wraps

from flask import request, current_app, g
from flask_jwt_extended import get_jwt_identity, jwt_required

from .errors import AppError
from .extensions import db
from .models import (
    AdminHospitalAssignment,
    Appointment,
    Doctor,
    DoctorHospitalAssignment,
    Hospital,
    Patient,
    Queue,
    QueueToken,
    ReceptionistHospitalAssignment,
    Role,
    User,
    UserStatus,
)


def get_current_tenant() -> Hospital | None:
    """Resolve the current tenant from the request (headers, subdomain, or domain)."""
    if hasattr(g, "current_tenant"):
        return g.current_tenant

    hospital_id = request.headers.get("X-Hospital-Id")
    tenant_slug = request.headers.get("X-Tenant-Slug")
    host = request.host.split(":")[0]

    tenant = None
    if hospital_id and hospital_id.isdigit():
        tenant = db.session.get(Hospital, int(hospital_id))
    elif tenant_slug:
        tenant = Hospital.query.filter_by(slug=tenant_slug).first()
    else:
        # Check custom domain
        tenant = Hospital.query.filter_by(custom_domain=host).first()

    g.current_tenant = tenant
    return tenant


def require_tenant():
    """Ensure a valid, active tenant context is present and has an active subscription."""
    tenant = get_current_tenant()
    if not tenant:
        raise AppError("Tenant context is required", 400, "tenant_required")

    if not tenant.is_active or tenant.subscription_status not in ["active", "trial"]:
        raise AppError("Tenant subscription is inactive or suspended", 403, "tenant_suspended")

    return tenant


def current_user() -> User:
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id)) if user_id else None
    if not user:
        raise AppError("Authentication required", 401, "auth_required")
    if user.status != UserStatus.ACTIVE:
        raise AppError("Account is not active", 403, "account_inactive")
    return user


def roles_required(*roles: Role):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            user = current_user()
            if user.role not in roles:
                raise AppError("Permission denied", 403, "permission_denied")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def hospital_ids_for_user(user: User) -> set[int]:
    if user.role == Role.SUPER_ADMIN:
        return set()
    if user.role == Role.ADMIN and user.admin_profile:
        return {a.hospital_id for a in user.admin_profile.hospital_assignments if a.is_active}
    if user.role == Role.DOCTOR and user.doctor_profile:
        return {a.hospital_id for a in user.doctor_profile.hospital_assignments if a.is_active}
    if user.role == Role.RECEPTIONIST and user.receptionist_profile:
        return {a.hospital_id for a in user.receptionist_profile.hospital_assignments if a.is_active}
    if user.role == Role.PHARMACIST and user.pharmacist_profile:
        return {a.hospital_id for a in user.pharmacist_profile.hospital_assignments if a.is_active}
    return set()


def can_access_hospital(user: User, hospital_id: int) -> bool:
    return user.role == Role.SUPER_ADMIN or hospital_id in hospital_ids_for_user(user)


def require_hospital_access(user: User, hospital_id: int):
    if not can_access_hospital(user, hospital_id):
        raise AppError("Hospital access denied", 403, "hospital_access_denied")


def doctor_can_access_patient(user: User, patient_id: int) -> bool:
    if user.role != Role.DOCTOR or not user.doctor_profile:
        return False
    return db.session.query(Appointment.id).filter_by(doctor_id=user.doctor_profile.id, patient_id=patient_id).first() is not None


def can_access_patient(user: User, patient_id: int, basic_only: bool = False) -> bool:
    if user.role == Role.SUPER_ADMIN:
        return True
    if user.role == Role.PATIENT:
        return bool(user.patient_profile and user.patient_profile.id == patient_id)
    if user.role == Role.DOCTOR:
        return doctor_can_access_patient(user, patient_id)
    if user.role in {Role.ADMIN, Role.RECEPTIONIST}:
        appt = Appointment.query.filter_by(patient_id=patient_id).first()
        return bool(appt and can_access_hospital(user, appt.hospital_id))
    return False


def require_patient_access(user: User, patient_id: int, basic_only: bool = False):
    if not can_access_patient(user, patient_id, basic_only):
        raise AppError("Patient access denied", 403, "patient_access_denied")


def require_appointment_access(user: User, appointment: Appointment):
    if user.role == Role.SUPER_ADMIN:
        return
    if user.role == Role.PATIENT and user.patient_profile and appointment.patient_id == user.patient_profile.id:
        return
    if user.role == Role.DOCTOR and user.doctor_profile and appointment.doctor_id == user.doctor_profile.id:
        return
    if user.role in {Role.ADMIN, Role.RECEPTIONIST} and can_access_hospital(user, appointment.hospital_id):
        return
    raise AppError("Appointment access denied", 403, "appointment_access_denied")


def register_security_headers(app):
    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not app.config.get("DEBUG"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
