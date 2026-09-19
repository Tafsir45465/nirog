from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func, and_, or_

from ..errors import AppError
from ..extensions import db
from ..models import (
    Appointment,
    Doctor,
    DoctorHospitalAssignment,
    Invoice,
    Patient,
    Prescription,
    Hospital,
    Role,
)
from ..security import current_user, require_hospital_access, get_current_tenant


bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@bp.route("/dashboard", methods=["GET"])
@jwt_required()
def analytics_dashboard():
    """Get comprehensive dashboard analytics for hospital admins."""
    user = current_user()
    tenant = get_current_tenant()
    hospital_id = request.args.get("hospital_id", type=int)

    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    # Date range
    days = request.args.get("days", default=30, type=int)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    # Query appointments
    appt_query = Appointment.query.filter(
        Appointment.created_at >= start_date,
        Appointment.created_at <= end_date
    )
    if hospital_id:
        appt_query = appt_query.filter_by(hospital_id=hospital_id)

    appointments = appt_query.all()

    # Metrics
    total_appointments = len(appointments)
    completed = sum(1 for a in appointments if a.status == "completed")
    cancelled = sum(1 for a in appointments if a.status == "cancelled")
    no_show = sum(1 for a in appointments if a.status == "no_show")

    # Revenue metrics
    inv_query = Invoice.query.filter(
        Invoice.created_at >= start_date,
        Invoice.created_at <= end_date,
        Invoice.deleted_at.is_(None)
    )
    if hospital_id:
        inv_query = inv_query.filter_by(hospital_id=hospital_id)

    invoices = inv_query.all()
    total_revenue = sum(float(inv.paid_amount) for inv in invoices)
    outstanding = sum(float(inv.due_amount) for inv in invoices if inv.status != "cancelled")

    # Doctor workload
    doc_query = db.session.query(
        Doctor.id,
        Doctor.user_id,
        func.count(Appointment.id).label("count")
    ).outerjoin(
        Appointment, Appointment.doctor_id == Doctor.id
    )

    if hospital_id:
        doc_query = doc_query.join(
            DoctorHospitalAssignment, DoctorHospitalAssignment.doctor_id == Doctor.id
        ).filter(DoctorHospitalAssignment.hospital_id == hospital_id)

    doc_query = doc_query.filter(
        Appointment.created_at >= start_date,
        Appointment.created_at <= end_date
    ).group_by(Doctor.id).order_by(func.count(Appointment.id).desc()).limit(10)

    top_doctors = doc_query.all()

    # Patient demographics
    patient_count_query = db.session.query(func.count(Patient.id).label("cnt")).filter(
        Patient.created_at >= start_date,
        Patient.created_at <= end_date
    )
    if hospital_id:
        patient_count_query = patient_count_query.join(
            Appointment, Appointment.patient_id == Patient.id
        ).filter(Appointment.hospital_id == hospital_id).distinct()

    new_patients = patient_count_query.scalar() or 0

    # Appointment status breakdown
    status_breakdown = {}
    for appt in appointments:
        s = appt.status
        status_breakdown[s] = status_breakdown.get(s, 0) + 1

    return jsonify({
        "data": {
            "summary": {
                "total_appointments": total_appointments,
                "completed": completed,
                "cancelled": cancelled,
                "no_show": no_show,
                "completion_rate": round(completed / total_appointments * 100, 1) if total_appointments > 0 else 0,
                "total_revenue": round(total_revenue, 2),
                "outstanding": round(outstanding, 2),
                "new_patients": new_patients,
            },
            "status_breakdown": status_breakdown,
            "top_doctors": [
                {
                    "doctor_id": d[0],
                    "user_id": d[1],
                    "appointments_count": d[2] or 0
                }
                for d in top_doctors
            ]
        }
    })


@bp.route("/daily-volume", methods=["GET"])
@jwt_required()
def daily_volume():
    """Get daily appointment volume for charting."""
    user = current_user()
    tenant = get_current_tenant()
    hospital_id = request.args.get("hospital_id", type=int)

    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    days = request.args.get("days", default=30, type=int)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    query = db.session.query(
        func.date(Appointment.created_at).label("date"),
        func.count(Appointment.id).label("count")
    ).filter(
        Appointment.created_at >= start_date,
        Appointment.created_at <= end_date
    )

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)

    query = query.group_by(func.date(Appointment.created_at)).order_by(
        func.date(Appointment.created_at)
    )

    results = query.all()
    labels = [str(r[0]) for r in results]
    data = [r[1] for r in results]

    return jsonify({
        "data": {
            "labels": labels,
            "data": data
        }
    })


@bp.route("/revenue-trend", methods=["GET"])
@jwt_required()
def revenue_trend():
    """Get daily revenue trend."""
    user = current_user()
    tenant = get_current_tenant()
    hospital_id = request.args.get("hospital_id", type=int)

    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    days = request.args.get("days", default=30, type=int)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    query = db.session.query(
        func.date(Invoice.created_at).label("date"),
        func.sum(Invoice.paid_amount).label("revenue")
    ).filter(
        Invoice.created_at >= start_date,
        Invoice.created_at <= end_date,
        Invoice.deleted_at.is_(None)
    )

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)

    query = query.group_by(func.date(Invoice.created_at)).order_by(
        func.date(Invoice.created_at)
    )

    results = query.all()
    labels = [str(r[0]) for r in results]
    data = [round(float(r[1]) if r[1] else 0, 2) for r in results]

    return jsonify({
        "data": {
            "labels": labels,
            "data": data
        }
    })


@bp.route("/doctor-workload", methods=["GET"])
@jwt_required()
def doctor_workload():
    """Get doctor workload metrics."""
    user = current_user()
    tenant = get_current_tenant()
    hospital_id = request.args.get("hospital_id", type=int)

    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    days = request.args.get("days", default=30, type=int)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    query = db.session.query(
        Doctor.id,
        Doctor.user_id,
        func.count(Appointment.id).label("total"),
        func.sum(
            (Appointment.status == "completed").cast(db.Integer)
        ).label("completed")
    ).outerjoin(
        Appointment, and_(
            Appointment.doctor_id == Doctor.id,
            Appointment.created_at >= start_date,
            Appointment.created_at <= end_date
        )
    )

    if hospital_id:
        query = query.join(
            DoctorHospitalAssignment, DoctorHospitalAssignment.doctor_id == Doctor.id
        ).filter(DoctorHospitalAssignment.hospital_id == hospital_id, DoctorHospitalAssignment.is_active == True)

    query = query.group_by(Doctor.id).order_by(
        func.count(Appointment.id).desc()
    ).limit(10)

    doctors = query.all()
    labels = []
    appointments = []
    completion = []

    for doc_id, user_id, total, comp in doctors:
        doc = db.session.get(Doctor, doc_id)
        if doc:
            labels.append(f"Dr. {doc.user.full_name}" if doc.user else f"Doctor #{doc_id}")
            appointments.append(total or 0)
            completion.append(round((comp or 0) / (total or 1) * 100, 1))

    return jsonify({
        "data": {
            "labels": labels,
            "appointments": appointments,
            "completion_rate": completion
        }
    })


@bp.route("/specialty-distribution", methods=["GET"])
@jwt_required()
def specialty_distribution():
    """Get appointment distribution by specialty."""
    user = current_user()
    tenant = get_current_tenant()
    hospital_id = request.args.get("hospital_id", type=int)

    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    days = request.args.get("days", default=30, type=int)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    from ..models import Specialty

    query = db.session.query(
        Specialty.name,
        func.count(Appointment.id).label("count")
    ).join(
        Doctor, Doctor.specialty_id == Specialty.id
    ).join(
        Appointment, Appointment.doctor_id == Doctor.id
    ).filter(
        Appointment.created_at >= start_date,
        Appointment.created_at <= end_date
    )

    if hospital_id:
        query = query.filter(Appointment.hospital_id == hospital_id)

    query = query.group_by(Specialty.id).order_by(func.count(Appointment.id).desc())

    results = query.all()
    labels = [r[0] for r in results]
    data = [r[1] for r in results]

    return jsonify({
        "data": {
            "labels": labels,
            "data": data
        }
    })
