from __future__ import annotations

from flask import Blueprint, request

from app.extensions import limiter, specialty_search_key
from app.models import Department, Doctor, DoctorDepartmentAssignment, DoctorHospitalAssignment, Hospital, Specialty, User, UserStatus
from app.utils.responses import ok

bp = Blueprint("public", __name__, url_prefix="/api")


@bp.get("/hospitals")
def list_hospitals():
    hospitals = Hospital.query.filter(Hospital.is_active.is_(True), Hospital.deleted_at.is_(None)).all()
    return ok({"hospitals": [h.to_dict() for h in hospitals]})


@bp.get("/specialties")
@bp.get("/catalogs/specialties")
def list_specialties():
    specialties = Specialty.query.filter(Specialty.is_active.is_(True)).all()
    return ok({"specialties": [s.to_dict() for s in specialties]})


@bp.get("/departments")
def list_departments():
    hospital_id = request.args.get("hospital_id", type=int)
    q = Department.query
    if hospital_id:
        q = q.filter(Department.hospital_id == hospital_id)
    departments = q.filter(Department.is_active.is_(True)).limit(200).all()
    return ok({"departments": [{"id": d.id, "name": d.name, "hospital_id": d.hospital_id, "specialty_id": d.specialty_id} for d in departments]})


@bp.get("/doctors")
@bp.get("/doctors/search")
@limiter.limit("90 per minute, 1200 per hour", key_func=specialty_search_key)
def search_doctors():
    args = request.args
    hospital_id = args.get("hospital_id", type=int)
    department_id = args.get("department_id", type=int)
    specialty_id = args.get("specialty_id", type=int)
    name = args.get("name", type=str)
    q = Doctor.query

    if hospital_id:
        q = q.join(Doctor.hospital_assignments).filter(DoctorHospitalAssignment.hospital_id == hospital_id, DoctorHospitalAssignment.is_active.is_(True))
    if department_id:
        q = q.join(Doctor.department_assignments).filter(DoctorDepartmentAssignment.department_id == department_id, DoctorDepartmentAssignment.is_active.is_(True))
    if specialty_id:
        q = q.filter(Doctor.specialty_id == specialty_id)
    if name:
        q = q.join(Doctor.user).filter(User.full_name.ilike(f"%{name}%"))

    q = q.filter(Doctor.verification_status == UserStatus.ACTIVE)
    doctors = q.limit(50).all()

    return ok({"doctors": [d.to_dict() for d in doctors]})
