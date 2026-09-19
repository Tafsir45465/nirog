from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import or_

from flask import current_app

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, AppointmentStatus, ConsentType, Doctor, DoctorSchedule, Hospital, Patient, User, utcnow
from app.services.audit import log_action
from app.services.consent import check_consent_status
from app.services.notifications import notify_appointment_booked, notify_appointment_cancelled


def local_tz():
    return ZoneInfo(current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka"))


def parse_local_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt


def doctor_has_assignment(doctor: Doctor, hospital_id: int) -> bool:
    return any(a.hospital_id == hospital_id and a.is_active for a in doctor.hospital_assignments)


def slot_in_schedule(doctor_id: int, hospital_id: int, start: datetime, end: datetime) -> bool:
    local_start = start.astimezone(local_tz())
    schedule = DoctorSchedule.query.filter_by(doctor_id=doctor_id, hospital_id=hospital_id, weekday=local_start.weekday(), is_active=True).first()
    if not schedule:
        return False
    t_start = local_start.time()
    t_end = end.astimezone(local_tz()).time()
    if t_start < schedule.start_time or t_end > schedule.end_time:
        return False
    if schedule.break_start and schedule.break_end and t_start < schedule.break_end and t_end > schedule.break_start:
        return False
    if schedule.max_appointments:
        day_start = local_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = Appointment.query.filter(
            Appointment.doctor_id == doctor_id,
            Appointment.hospital_id == hospital_id,
            Appointment.scheduled_start >= day_start,
            Appointment.scheduled_start < day_end,
            Appointment.status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED]),
        ).count()
        if count >= schedule.max_appointments:
            return False
    return True


def create_appointment(actor: User, patient_id: int, doctor_id: int, hospital_id: int, scheduled_start: str, appointment_type="in_person", reason=None, department_id=None):
    doctor = db.session.get(Doctor, doctor_id)
    hospital = db.session.get(Hospital, hospital_id)
    patient = db.session.get(Patient, patient_id)
    if not doctor or not hospital or not patient:
        raise AppError("Patient, doctor, or hospital not found", 404, "not_found")
    if not hospital.is_active or not doctor.is_bookable() or not doctor_has_assignment(doctor, hospital_id):
        raise AppError("Doctor is not bookable at this hospital", 400, "doctor_not_bookable")

    start = parse_local_datetime(scheduled_start)
    duration = doctor.appointment_duration_minutes or 15
    end = start + timedelta(minutes=duration)
    if start <= utcnow():
        raise AppError("Appointment must be in the future", 400, "invalid_time")
    if start.minute % duration != 0:
        raise AppError("Appointment time does not align with doctor slot duration", 400, "invalid_slot")
    if not slot_in_schedule(doctor_id, hospital_id, start, end):
        raise AppError("Invalid appointment slot", 400, "invalid_slot")

    existing = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.hospital_id == hospital_id,
        Appointment.status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED]),
        Appointment.scheduled_start < end,
        Appointment.scheduled_end > start,
    ).first()
    if existing:
        raise AppError("Slot already booked", 409, "double_booking")

    # Check patient consent before booking
    consent_result = check_consent_status(patient_id, hospital_id, ConsentType.TREATMENT)
    if not consent_result["has_consent"]:
        raise AppError(
            "Patient consent for treatment is required before booking an appointment. "
            "Please complete the consent form first.",
            403,
            "consent_required",
        )

    appt = Appointment(patient_id=patient_id, doctor_id=doctor_id, hospital_id=hospital_id, department_id=department_id, scheduled_start=start, scheduled_end=end, appointment_type=appointment_type, reason=reason, status=AppointmentStatus.BOOKED)
    db.session.add(appt)
    db.session.flush()
    notify_appointment_booked(appt)
    log_action(actor, "appointment.created", "Appointment", appt.id, after=appt.to_dict())
    return appt


def cancel_appointment(actor: User, appointment: Appointment, reason: str | None = None):
    before = appointment.to_dict()
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancelled_by_user_id = actor.id
    appointment.cancellation_reason = reason
    notify_appointment_cancelled(appointment)
    log_action(actor, "appointment.cancelled", "Appointment", appointment.id, before=before, after=appointment.to_dict())
    return appointment
