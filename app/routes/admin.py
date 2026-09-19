from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.errors import AppError
from app.extensions import db, limiter
from app.models import (
    AdminHospitalAssignment,
    AdminProfile,
    Doctor,
    DoctorHospitalAssignment,
    DoctorDepartmentAssignment,
    Department,
    Hospital,
    Patient,
    ReceptionistProfile,
    ReceptionistHospitalAssignment,
    Role,
    Specialty,
    User,
    UserStatus,
)
from app.models import Appointment, AppointmentStatus, DoctorSchedule
from app.security import current_user, require_hospital_access
from app.services.audit import log_action
from app.services.queues import get_or_create_queue
from app.utils.responses import ok

bp = Blueprint("admin", __name__, url_prefix="/api")


def is_super_admin(user: User) -> bool:
    return user.role == Role.SUPER_ADMIN


def can_manage_doctors(user: User) -> bool:
    return is_super_admin(user) or bool(
        user.role == Role.ADMIN and user.admin_profile and user.admin_profile.can_manage_doctors
    )


@bp.get("/admin/doctors")
@jwt_required()
def list_doctors_admin():
    user = current_user()
    if not can_manage_doctors(user):
        raise AppError("Permission denied", 403, "permission_denied")

    query = Doctor.query.join(Doctor.user)
    if not is_super_admin(user):
        allowed = require_admin_hospital_ids(user)
        query = query.join(Doctor.hospital_assignments).filter(
            DoctorHospitalAssignment.hospital_id.in_(allowed),
            DoctorHospitalAssignment.is_active.is_(True),
        )

    doctors = query.order_by(Doctor.created_at.desc()).distinct().limit(200).all()
    data = []
    for doctor in doctors:
        entry = doctor.to_dict()
        entry["email"] = doctor.user.email
        entry["phone"] = doctor.user.phone
        entry["hospital_ids"] = [a.hospital_id for a in doctor.hospital_assignments if a.is_active]
        data.append(entry)
    return ok({"doctors": data})


@bp.get("/admin/patients")
@jwt_required()
def list_patients_admin():
    user = current_user()
    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST}:
        raise AppError("Permission denied", 403, "permission_denied")

    search = (request.args.get("search") or "").strip()
    query = Patient.query.join(Patient.user)
    if search:
        pattern = f"%{search}%"
        query = query.filter((User.email.ilike(pattern)) | (User.phone.ilike(pattern)) | (User.full_name.ilike(pattern)) | (Patient.patient_code.ilike(pattern)))

    if not is_super_admin(user):
        allowed = hospital_ids_for_staff(user)
        if not allowed:
            return ok({"patients": []})
        query = query.join(Appointment).filter(Appointment.hospital_id.in_(allowed))

    patients = query.order_by(Patient.created_at.desc()).distinct().limit(100).all()
    return ok({"patients": [p.to_dict() for p in patients]})


@bp.get("/admin/schedules")
@jwt_required()
def list_schedules():
    user = current_user()
    if not can_manage_doctors(user):
        raise AppError("Permission denied", 403, "permission_denied")
    doctor_id = request.args.get("doctor_id", type=int)
    if not doctor_id:
        raise AppError("doctor_id required", 400, "validation_error")
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        raise AppError("Doctor not found", 404, "not_found")
    if not is_super_admin(user):
        allowed = require_admin_hospital_ids(user)
        if not any(a.hospital_id in allowed for a in doctor.hospital_assignments if a.is_active):
            raise AppError("Hospital access denied", 403, "hospital_access_denied")
    schedules = DoctorSchedule.query.filter_by(doctor_id=doctor.id).order_by(DoctorSchedule.weekday).all()
    return ok({"schedules": [serialize_schedule(s) for s in schedules]})


@bp.post("/admin/schedules")
@jwt_required()
def save_schedule():
    user = current_user()
    if not can_manage_doctors(user):
        raise AppError("Permission denied", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    required = ("doctor_id", "hospital_id", "weekday", "start_time", "end_time")
    for field in required:
        if data.get(field) is None:
            raise AppError(f"{field} required", 400, "validation_error")
    doctor = db.session.get(Doctor, data["doctor_id"])
    if not doctor:
        raise AppError("Doctor not found", 404, "not_found")
    if not any(a.hospital_id == data["hospital_id"] and a.is_active for a in doctor.hospital_assignments):
        raise AppError("Doctor is not assigned to this hospital", 400, "invalid_assignment")
    if not is_super_admin(user):
        require_hospital_access(user, data["hospital_id"])

    from datetime import time
    try:
        start_time = time.fromisoformat(data["start_time"])
        end_time = time.fromisoformat(data["end_time"])
        break_start = time.fromisoformat(data["break_start"]) if data.get("break_start") else None
        break_end = time.fromisoformat(data["break_end"]) if data.get("break_end") else None
    except ValueError:
        raise AppError("Invalid time format; use HH:MM", 400, "validation_error")
    if start_time >= end_time:
        raise AppError("End time must be after start time", 400, "validation_error")
    schedule = DoctorSchedule.query.filter_by(doctor_id=doctor.id, hospital_id=data["hospital_id"], weekday=data["weekday"]).first()
    if not schedule:
        schedule = DoctorSchedule(doctor_id=doctor.id, hospital_id=data["hospital_id"], weekday=data["weekday"], start_time=start_time, end_time=end_time)
        db.session.add(schedule)
    schedule.department_id = data.get("department_id")
    schedule.start_time = start_time
    schedule.end_time = end_time
    schedule.break_start = break_start
    schedule.break_end = break_end
    schedule.appointment_duration_minutes = data.get("appointment_duration_minutes", doctor.appointment_duration_minutes)
    schedule.max_appointments = data.get("max_appointments")
    schedule.is_active = data.get("is_active", True)
    db.session.commit()
    return ok({"schedule": serialize_schedule(schedule)}, "Schedule saved")


def require_admin_hospital_ids(user: User) -> set[int]:
    allowed = {a.hospital_id for a in user.admin_profile.hospital_assignments if a.is_active} if user.admin_profile else set()
    if not allowed:
        raise AppError("No hospital assignment", 403, "hospital_access_denied")
    return allowed


def hospital_ids_for_staff(user: User) -> set[int]:
    if user.role == Role.ADMIN and user.admin_profile:
        return {a.hospital_id for a in user.admin_profile.hospital_assignments if a.is_active}
    if user.role == Role.RECEPTIONIST and user.receptionist_profile:
        return {a.hospital_id for a in user.receptionist_profile.hospital_assignments if a.is_active}
    return set()


def serialize_schedule(schedule: DoctorSchedule) -> dict:
    return {
        "id": schedule.id,
        "doctor_id": schedule.doctor_id,
        "hospital_id": schedule.hospital_id,
        "department_id": schedule.department_id,
        "weekday": schedule.weekday,
        "start_time": schedule.start_time.isoformat(timespec="minutes"),
        "end_time": schedule.end_time.isoformat(timespec="minutes"),
        "break_start": schedule.break_start.isoformat(timespec="minutes") if schedule.break_start else None,
        "break_end": schedule.break_end.isoformat(timespec="minutes") if schedule.break_end else None,
        "appointment_duration_minutes": schedule.appointment_duration_minutes,
        "max_appointments": schedule.max_appointments,
        "is_active": schedule.is_active,
    }


@bp.post("/doctors")
@jwt_required()
@limiter.limit("20 per hour")
def create_doctor():
    user = current_user()
    if not is_super_admin(user) and not (user.role == Role.ADMIN and user.admin_profile and user.admin_profile.can_manage_doctors):
        raise AppError("Permission denied", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    required = ["full_name", "email", "password", "license_number", "specialty_id", "hospital_ids"]
    for f in required:
        if not data.get(f):
            raise AppError(f"{f} required", 400, "validation_error")
    email = data["email"].lower()
    if User.query.filter_by(email=email).first():
        raise AppError("Email exists", 409, "email_exists")

    person = User(full_name=data["full_name"], email=email, phone=data.get("phone"), role=Role.DOCTOR, status=UserStatus.PENDING)
    person.set_password(data["password"])
    db.session.add(person)
    db.session.flush()

    specialty = db.session.get(Specialty, data["specialty_id"])
    doctor = Doctor(
        user_id=person.id,
        specialty_id=data["specialty_id"],
        professional_title=data.get("professional_title", "Dr."),
        qualifications=data.get("qualifications"),
        license_number=data["license_number"],
        experience_years=data.get("experience_years", 0),
        consultation_fee=data.get("consultation_fee", 0),
        appointment_duration_minutes=data.get("appointment_duration_minutes", 15),
        bio=data.get("bio"),
        languages=data.get("languages"),
    )
    db.session.add(doctor)
    db.session.flush()

    for hid in data["hospital_ids"]:
        assignment = DoctorHospitalAssignment(doctor_id=doctor.id, hospital_id=hid, is_active=True)
        db.session.add(assignment)

    if data.get("department_ids"):
        for did in data["department_ids"]:
            db.session.add(DoctorDepartmentAssignment(doctor_id=doctor.id, department_id=did, is_active=True))

    log_action(user, "doctor.created", "Doctor", doctor.id)
    db.session.commit()
    return ok({"user": person.to_public_dict(), "doctor": doctor.to_dict()}, "Doctor created", 201)


@bp.post("/doctors/<int:doctor_id>/approve")
@jwt_required()
def approve_doctor(doctor_id):
    user = current_user()
    if not is_super_admin(user):
        raise AppError("Permission denied", 403, "permission_denied")
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        raise AppError("Doctor not found", 404, "not_found")
    doctor.verification_status = UserStatus.ACTIVE
    doctor.approved_by_user_id = user.id
    doctor.approved_at = None
    import datetime
    from datetime import datetime, timezone
    doctor.approved_at = datetime.now(timezone.utc)
    log_action(user, "doctor.approved", "Doctor", doctor.id)
    db.session.commit()
    return ok(doctor.to_dict(), "Doctor approved")


@bp.post("/hospitals")
@jwt_required()
def create_hospital():
    user = current_user()
    if not is_super_admin(user):
        raise AppError("Permission denied", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    required = ["name", "address", "phone"]
    for f in required:
        if not data.get(f):
            raise AppError(f"{f} required", 400, "validation_error")
    hospital = Hospital(name=data["name"], slug=data.get("slug", data["name"].lower().replace(" ", "-")), address=data["address"], phone=data["phone"], email=data.get("email"), website=data.get("website"), description=data.get("description"), emergency_info=data.get("emergency_info"), opening_hours=data.get("opening_hours"))
    db.session.add(hospital)
    log_action(user, "hospital.created", "Hospital", hospital.id)
    db.session.commit()
    return ok(hospital.to_dict(), "Hospital created", 201)


@bp.post("/receptionists")
@jwt_required()
def create_receptionist():
    user = current_user()
    if not is_super_admin(user) and not (user.role == Role.ADMIN and user.admin_profile and user.admin_profile.can_manage_doctors):
        raise AppError("Permission denied", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    required = ["full_name", "email", "password", "hospital_ids"]
    for f in required:
        if not data.get(f):
            raise AppError(f"{f} required", 400, "validation_error")
    email = data["email"].lower()
    if User.query.filter_by(email=email).first():
        raise AppError("Email exists", 409, "email_exists")
    person = User(full_name=data["full_name"], email=email, phone=data.get("phone"), role=Role.RECEPTIONIST, status=UserStatus.ACTIVE)
    person.set_password(data["password"])
    db.session.add(person)
    db.session.flush()
    rec = ReceptionistProfile(user_id=person.id, employee_code=data.get("employee_code"))
    db.session.add(rec)
    for hid in data["hospital_ids"]:
        db.session.add(ReceptionistHospitalAssignment(receptionist_profile_id=rec.id, hospital_id=hid, is_active=True))
    log_action(user, "receptionist.created", "Receptionist", rec.id)
    db.session.commit()
    return ok({"user": person.to_public_dict(), "receptionist": {"id": rec.id}}, "Receptionist created", 201)


@bp.post("/patients")
@jwt_required()
def create_patient():
    user = current_user()
    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST}:
        raise AppError("Permission denied", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    required = ["full_name", "email"]
    for f in required:
        if not data.get(f):
            raise AppError(f"{f} required", 400, "validation_error")
    email = data["email"].lower()
    if User.query.filter_by(email=email).first():
        raise AppError("Email exists", 409, "email_exists")
    person = User(full_name=data["full_name"], email=email, phone=data.get("phone"), role=Role.PATIENT, status=UserStatus.ACTIVE)
    person.set_password(data.get("password", "Temp@123"))
    db.session.add(person)
    db.session.flush()
    from datetime import datetime
    patient = Patient(
        user_id=person.id,
        patient_code=f"P{person.id:06d}",
        date_of_birth=datetime.fromisoformat(data["date_of_birth"]).date() if data.get("date_of_birth") else None,
        gender=data.get("gender"),
        address=data.get("address"),
        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
        blood_group=data.get("blood_group"),
        basic_health_info=data.get("basic_health_info"),
    )
    db.session.add(patient)
    log_action(user, "patient.created", "Patient", patient.id)
    db.session.commit()
    return ok({"user": person.to_public_dict(), "patient": patient.to_dict()}, "Patient created", 201)


@bp.post("/admin/profile")
@jwt_required()
def update_admin_profile():
    user = current_user()
    if user.role != Role.ADMIN:
        raise AppError("Admins only", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    if not user.admin_profile:
        user.admin_profile = AdminProfile(user_id=user.id)
    for field in ("title", "can_manage_doctors", "can_manage_catalogs"):
        if field in data:
            setattr(user.admin_profile, field, data[field])
    db.session.commit()
    return ok(user.to_public_dict(), "Updated")


@bp.post("/admin/hospitals")
@jwt_required()
def assign_admin_hospital():
    user = current_user()
    if user.role != Role.ADMIN:
        raise AppError("Admins only", 403, "permission_denied")
    data = request.get_json(silent=True) or {}
    if not user.admin_profile:
        user.admin_profile = AdminProfile(user_id=user.id)
    existing = {a.hospital_id for a in user.admin_profile.hospital_assignments}
    for hid in data.get("hospital_ids", []):
        if hid not in existing:
            db.session.add(AdminHospitalAssignment(admin_profile_id=user.admin_profile.id, hospital_id=hid, is_active=True))
    db.session.commit()
    return ok({"hospital_ids": [a.hospital_id for a in user.admin_profile.hospital_assignments]})