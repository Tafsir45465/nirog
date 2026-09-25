"""Mobile-optimized API endpoints for Nirog PWA."""

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.extensions import db
from app.models import User, Hospital, Appointment, AppointmentStatus, Prescription, MedicalTest, LabReport
from app.utils.responses import ok, error
from app.security import current_user, require_hospital_access
from datetime import datetime, timedelta

bp = Blueprint("mobile", __name__, url_prefix="/api/mobile")


@bp.get("/dashboard")
@jwt_required()
def mobile_dashboard():
    """Return aggregated data for patient dashboard in a single call."""
    user = current_user()
    if not user.patient_profile:
        return error("Patient profile not found", 404, "not_found")
    patient = user.patient_profile
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        # default to first hospital assignment
        hospital_id = patient.hospitals[0].id if patient.hospitals else None
    if not hospital_id:
        return error("No hospital associated", 400, "no_hospital")
    require_hospital_access(user, hospital_id)

    # Upcoming appointments (next 7 days)
    now = datetime.utcnow()
    upcoming = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.hospital_id == hospital_id,
        Appointment.scheduled_start >= now,
        Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED, AppointmentStatus.CHECKED_IN, AppointmentStatus.WAITING, AppointmentStatus.IN_CONSULTATION])
    ).order_by(Appointment.scheduled_start).limit(5).all()

    # Completed appointments count (last 30 days)
    thirty_days_ago = now - timedelta(days=30)
    completed_count = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.hospital_id == hospital_id,
        Appointment.scheduled_start >= thirty_days_ago,
        Appointment.status == AppointmentStatus.COMPLETED
    ).count()

    # Prescriptions count (active)
    prescriptions_count = Prescription.query.filter_by(
        patient_id=patient.id,
        hospital_id=hospital_id,
        status='finalized'
    ).count()

    # Lab results count (last 7 days)
    week_ago = now - timedelta(days=7)
    recent_labs = LabReport.query.join(MedicalTest).filter(
        LabReport.patient_id == patient.id,
        LabReport.hospital_id == hospital_id,
        LabReport.created_at >= week_ago
    ).count()

    # Next token (if any waiting)
    from app.models import QueueToken, QueueStatus
    next_token = QueueToken.query.filter_by(
        patient_id=patient.id,
        hospital_id=hospital_id,
        status=QueueStatus.WAITING
    ).order_by(QueueToken.position).first()

    data = {
        "hospital_id": hospital_id,
        "hospital_name": Hospital.query.get(hospital_id).name if hospital_id else None,
        "upcoming_appointments": [
            {
                "id": a.id,
                "doctor_name": a.doctor_name,
                "specialty": a.specialty_name,
                "scheduled_start": a.scheduled_start.isoformat() if a.scheduled_start else None,
                "status": a.status.value,
                "reason": a.reason
            }
            for a in upcoming
        ],
        "completed_count": completed_count,
        "prescriptions_count": prescriptions_count,
        "recent_labs_count": recent_labs,
        "next_token": {
            "token_number": next_token.token_number if next_token else None,
            "position": next_token.position if next_token else None,
            "estimated_wait": next_token.wait_estimate_minutes if next_token else None
        } if next_token else None
    }
    return ok(data)


@bp.get("/appointments")
@jwt_required()
def mobile_appointments():
    """Paginated list of appointments for mobile."""
    user = current_user()
    if not user.patient_profile:
        return error("Patient profile not found", 404, "not_found")
    patient = user.patient_profile
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        hospital_id = patient.hospitals[0].id if patient.hospitals else None
    if not hospital_id:
        return error("No hospital associated", 400, "no_hospital")
    require_hospital_access(user, hospital_id)

    # pagination
    try:
        limit = min(int(request.args.get("limit", 20)), 100)  # max 100
    except ValueError:
        limit = 20
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0

    # filter params
    status = request.args.get("status")
    start_date = request.args.get("start_date")  # YYYY-MM-DD
    end_date = request.args.get("end_date")

    query = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.hospital_id == hospital_id
    )
    if status:
        try:
            status_enum = AppointmentStatus(status)
            query = query.filter(Appointment.status == status_enum)
        except ValueError:
            pass  # ignore invalid status
    if start_date:
        try:
            start = datetime.fromisoformat(start_date)
            query = query.filter(Appointment.scheduled_start >= start)
        except ValueError:
            pass
    if end_date:
            try:
                end = datetime.fromisoformat(end_date)
                query = query.filter(Appointment.scheduled_start <= end)
            except ValueError:
                pass

    total = query.count()
    appointments = query.order_by(Appointment.scheduled_start.desc()).offset(offset).limit(limit).all()

    data = {
        "total": total,
        "limit": limit,
        "offset": offset,
        "appointments": [
            {
                "id": a.id,
                "doctor_name": a.doctor_name,
                "hospital_name": a.hospital_name,
                "specialty": a.specialty_name,
                "scheduled_start": a.scheduled_start.isoformat() if a.scheduled_start else None,
                "scheduled_end": a.scheduled_end.isoformat() if a.scheduled_end else None,
                "status": a.status.value,
                "reason": a.reason,
                "appointment_type": a.appointment_type.value if a.appointment_type else None
            }
            for a in appointments
        ]
    }
    return ok(data)


@bp.post("/appointments")
@jwt_required()
def mobile_create_appointment():
    """Create an appointment (optimistic for PWA)."""
    user = current_user()
    if not user.patient_profile:
        return error("Patient profile not found", 404, "not_found")
    patient = user.patient_profile
    data = request.get_json(silent=True) or {}

    doctor_id = data.get("doctor_id")
    hospital_id = data.get("hospital_id")
    scheduled_start_str = data.get("scheduled_start")
    reason = data.get("reason", "")
    appointment_type_str = data.get("appointment_type", "in_person")

    if not doctor_id or not hospital_id or not scheduled_start_str:
        return error("doctor_id, hospital_id, scheduled_start are required", 400, "missing_fields")

    try:
        hospital_id = int(hospital_id)
        doctor_id = int(doctor_id)
        scheduled_start = datetime.fromisoformat(scheduled_start_str)
    except (ValueError, TypeError):
        return error("Invalid doctor_id, hospital_id, or scheduled_start format", 400, "invalid_format")

    # verify access
    require_hospital_access(user, hospital_id)

    # optional: verify doctor belongs to hospital
    from app.models import Doctor, DoctorHospitalAssignment
    doc = Doctor.query.get(doctor_id)
    if not doc or not DoctorHospitalAssignment.query.filter_by(doctor_id=doctor_id, hospital_id=hospital_id, is_active=True).first():
        return error("Doctor not associated with this hospital", 400, "bad_doctor_hospital")

    # create appointment
    from app.models import Appointment, AppointmentStatus, AppointmentType
    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doctor_id,
        hospital_id=hospital_id,
        scheduled_start=scheduled_start,
        reason=reason,
        status=AppointmentStatus.BOOKED,
        appointment_type=AppointmentType(appointment_type_str) if appointment_type_str else AppointmentType.IN_PERSON
    )
    db.session.add(appt)
    db.session.commit()  # generate ID

    # also create a queue token? maybe later when checked-in.

    return ok(data={"appointment_id": appt.id}, message="Appointment created")


@bp.get("/prescriptions")
@jwt_required()
def mobile_prescriptions():
    """Paginated prescriptions for mobile."""
    user = current_user()
    if not user.patient_profile:
        return error("Patient profile not found", 404, "not_found")
    patient = user.patient_profile
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        hospital_id = patient.hospitals[0].id if patient.hospitals else None
    if not hospital_id:
        return error("No hospital associated", 400, "no_hospital")
    require_hospital_access(user, hospital_id)

    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = Prescription.query.filter_by(
        patient_id=patient.id,
        hospital_id=hospital_id
    ).order_by(Prescription.finalized_at.desc().nullslast(), Prescription.created_at.desc())

    total = query.count()
    prescriptions = query.offset(offset).limit(limit).all()

    data = {
        "total": total,
        "limit": limit,
        "offset": offset,
        "prescriptions": [
            {
                "id": p.id,
                "doctor_name": p.doctor_name,
                "hospital_name": p.hospital_name,
                "diagnosis_summary": p.diagnosis_summary,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "finalized_at": p.finalized_at.isoformat() if p.finalized_at else None
            }
            for p in prescriptions
        ]
    }
    return ok(data)


@bp.get("/lab-results")
@jwt_required()
def mobile_lab_results():
    """Paginated lab results for mobile."""
    user = current_user()
    if not user.patient_profile:
        return error("Patient profile not found", 404, "not_found")
    patient = user.patient_profile
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        hospital_id = patient.hospitals[0].id if patient.hospitals else None
    if not hospital_id:
        return error("No hospital associated", 400, "no_hospital")
    require_hospital_access(user, hospital_id)

    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = LabReport.query.filter_by(
        patient_id=patient.id,
        hospital_id=hospital_id
    ).order_by(LabReport.created_at.desc())

    total = query.count()
    results = query.offset(offset).limit(limit).all()

    data = {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [
            {
                "id": r.id,
                "test_name": r.test_name,
                "value": r.value,
                "reference_range": r.reference_range,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "file_url": r.file_url
            }
            for r in results
        ]
    }
    return ok(data)
