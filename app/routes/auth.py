from __future__ import annotations

from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, request
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity

from app.errors import AppError
from app.extensions import db, limiter
from app.models import Patient, Role, User, UserStatus, utcnow
from app.services.audit import log_action
from app.utils.responses import ok

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def require_json():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise AppError("Invalid JSON", 400, "invalid_json")
    return data


@bp.post("/register")
@bp.post("/auth/register")
@limiter.limit("10 per hour")
def register_patient():
    data = require_json()
    for field in ["full_name", "email", "password"]:
        if not data.get(field):
            raise AppError(f"{field} is required", 400, "validation_error")
    try:
        email = validate_email(data["email"]).normalized
    except EmailNotValidError as exc:
        raise AppError("Invalid email", 400, "invalid_email", str(exc))
    if User.query.filter_by(email=email).first():
        raise AppError("Email already registered", 409, "email_exists")
    user = User(email=email, phone=data.get("phone"), full_name=data["full_name"].strip(), role=Role.PATIENT, status=UserStatus.ACTIVE)
    user.set_password(data["password"])
    db.session.add(user)
    db.session.flush()
    dob = datetime.fromisoformat(data["date_of_birth"]).date() if data.get("date_of_birth") else None
    patient = Patient(user_id=user.id, patient_code=f"P{user.id:06d}", date_of_birth=dob, gender=data.get("gender"), address=data.get("address"), emergency_contact_name=data.get("emergency_contact_name"), emergency_contact_phone=data.get("emergency_contact_phone"), blood_group=data.get("blood_group"), basic_health_info=data.get("basic_health_info"))
    db.session.add(patient)
    log_action(user, "patient.registered", "Patient", patient.id)
    db.session.commit()
    return ok({"user": user.to_public_dict(), "patient": patient.to_dict()}, "Patient registered", 201)


@bp.post("/login")
@bp.post("/auth/login")
@limiter.limit("20 per hour")
def login():
    data = require_json()
    user = User.query.filter_by(email=(data.get("email") or "").lower()).first()
    if not user or not user.check_password(data.get("password", "")):
        if user:
            user.failed_login_count += 1
            db.session.commit()
        raise AppError("Invalid credentials", 401, "invalid_credentials")
    if user.status != UserStatus.ACTIVE:
        raise AppError("Account is not active", 403, "account_inactive")
    user.failed_login_count = 0
    user.last_login_at = utcnow()
    log_action(user, "auth.login", "User", user.id)
    db.session.commit()
    claims = {"role": user.role.value}
    return ok({"access_token": create_access_token(identity=str(user.id), additional_claims=claims), "refresh_token": create_refresh_token(identity=str(user.id), additional_claims=claims), "user": user.to_public_dict()}, "Login successful")


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user or user.status != UserStatus.ACTIVE:
        raise AppError("Account is not active", 403, "account_inactive")
    return ok({"access_token": create_access_token(identity=str(user.id), additional_claims={"role": user.role.value})})


@bp.post("/logout")
@jwt_required()
def logout():
    return ok(None, "Logout successful")


@bp.post("/password-reset/request")
def password_reset_request():
    return ok(None, "If the account exists, password reset instructions will be sent")
