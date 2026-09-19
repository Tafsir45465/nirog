"""Follow-up and reminder management routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, Consultation, AppointmentStatus
from app.security import current_user, require_hospital_access, roles_required
from app.services.reminders import (
    get_appointments_needing_reminder,
    send_appointment_reminder,
    send_follow_up_reminder,
    check_and_send_reminders,
)
from app.utils.responses import ok, error

bp = Blueprint("reminders", __name__, url_prefix="/api/reminders")


@bp.get("/scheduled-reminders")
@jwt_required()
@roles_required("admin", "super_admin")
def get_scheduled_reminders():
    """Get appointments due for reminders (for admin dashboard)."""
    hospital_id = request.args.get("hospital_id", type=int)
    if hospital_id:
        require_hospital_access(current_user(), hospital_id)
    
    # Get both 24h and 2h reminders
    appointments_24h = get_appointments_needing_reminder("24h", hospital_id)
    appointments_2h = get_appointments_needing_reminder("2h", hospital_id)
    
    # Format for response
    formatted_24h = []
    for appt in appointments_24h:
        times = get_reminder_times_legacy(appt.scheduled_start)
        formatted_24h.append({
            "appointment_id": appt.id,
            "patient_id": appt.patient_id,
            "patient_name": appt.patient.user.full_name if appt.patient.user else "Unknown",
            "doctor_id": appt.doctor_id,
            "doctor_name": appt.doctor.user.full_name if appt.doctor.user else "Unknown",
            "hospital_id": appt.hospital_id,
            "scheduled_start": appt.scheduled_start.isoformat(),
            "reminder_window": "24 hours before",
        })
    
    formatted_2h = []
    for appt in appointments_2h:
        formatted_2h.append({
            "appointment_id": appt.id,
            "patient_id": appt.patient_id,
            "patient_name": appt.patient.user.full_name if appt.patient.user else "Unknown",
            "doctor_id": appt.doctor_id,
            "doctor_name": appt.doctor.user.full_name if appt.doctor.user else "Unknown",
            "hospital_id": appt.hospital_id,
            "scheduled_start": appt.scheduled_start.isoformat(),
            "reminder_window": "2 hours before",
        })
    
    return ok(
        data={
            "reminders_24h_pending": len(formatted_24h),
            "reminders_2h_pending": len(formatted_2h),
            "reminders_24h": formatted_24h,
            "reminders_2h": formatted_2h,
        }
    )


def get_reminder_times_legacy(scheduled_start):
    """Legacy function to get reminder times - needed for formatting."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from flask import current_app
    
    local_tz = current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka")
    tz = ZoneInfo(local_tz)
    start_local = scheduled_start.astimezone(tz)
    
    reminder_24h_local = start_local - timedelta(hours=24)
    reminder_2h_local = start_local - timedelta(hours=2)
    
    return {
        "reminder_24h_local": reminder_24h_local.isoformat(),
        "reminder_2h_local": reminder_2h_local.isoformat(),
    }


@bp.post("/send-reminder/<int:appointment_id>")
@jwt_required()
def send_manual_reminder(appointment_id: int):
    """Manually send a reminder for a specific appointment."""
    user = current_user()
    
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        raise AppError("Appointment not found", 404, "not_found")
    
    # Check access
    from app.security import can_access_patient
    if not can_access_patient(user, appointment.patient_id):
        raise AppError("Access denied", 403, "access_denied")
    
    data = request.get_json(silent=True) or {}
    reminder_type = data.get("reminder_type", "24h")  # "24h" or "2h"
    
    try:
        logs = send_appointment_reminder(appointment, reminder_type=reminder_type, force=True)
        db.session.commit()
        return ok(
            data={
                "appointment_id": appointment_id,
                "reminder_type": reminder_type,
                "sent_count": len([l for l in logs if l.status in ["sent", "logged"]]),
                "failed_count": len([l for l in logs if l.status == "failed"]),
            },
            message="Reminder sent successfully",
        )
    except Exception as e:
        db.session.rollback()
        raise AppError(f"Failed to send reminder: {str(e)}", 500, "reminder_failed")


@bp.post("/send-follow-up/<int:consultation_id>")
@jwt_required()
def send_manual_follow_up(consultation_id: int):
    """Manually send a follow-up consultation reminder."""
    user = current_user()
    
    consultation = db.session.get(Consultation, consultation_id)
    if not consultation:
        raise AppError("Consultation not found", 404, "not_found")
    
    # Check access
    from app.security import can_access_patient
    if not can_access_patient(user, consultation.patient_id):
        raise AppError("Access denied", 403, "access_denied")
    
    try:
        logs = send_follow_up_reminder(consultation)
        db.session.commit()
        return ok(
            data={
                "consultation_id": consultation_id,
                "follow_up_date": str(consultation.follow_up_date) if consultation.follow_up_date else None,
                "sent_count": len(logs),
            },
            message="Follow-up reminder sent successfully",
        )
    except Exception as e:
        db.session.rollback()
        raise AppError(f"Failed to send follow-up reminder: {str(e)}", 500, "reminder_failed")


@bp.post("/check-and-send")
@jwt_required()
@roles_required("admin", "super_admin")
def check_and_send_now():
    """Manually trigger the reminder scheduler.
    
    This runs the check_and_send_reminders function and returns results.
    Typically called by cron job or scheduled task.
    """
    hospital_id = request.args.get("hospital_id", type=int)
    if hospital_id:
        require_hospital_access(current_user(), hospital_id)
    
    results = check_and_send_reminders(hospital_id)
    return ok(data=results, message="Reminder check completed")


@bp.get("/my-upcoming")
@jwt_required()
def get_my_upcoming_appointments():
    """Get current user's upcoming appointments with reminder status."""
    user = current_user()
    
    if user.role != "patient" and not user.patient_profile:
        raise AppError("Only patients can view their appointments", 403, "permission_denied")
    
    patient_id = user.patient_profile.id if user.patient_profile else None
    
    # Get upcoming booked appointments
    from datetime import datetime
    now = datetime.now(timezone.utc)
    
    appointments = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.scheduled_start > now,
    ).order_by(Appointment.scheduled_start.asc()).limit(10).all()
    
    # Check reminder status for each
    from app.services.reminders import get_appointments_needing_reminder
    
    result = []
    for appt in appointments:
        # Check if this appt needs a 24h or 2h reminder
        needs_24h = False
        needs_2h = False
        
        # Simple check: if appointment is within 25h and 3h respectively
        now = datetime.now(timezone.utc)
        twenty_five_h_before = appt.scheduled_start - timedelta(hours=25)
        three_h_before = appt.scheduled_start - timedelta(hours=3)
        
        if twenty_five_h_before <= now <= appt.scheduled_start:
            needs_24h = True
        if three_h_before <= now <= appt.scheduled_start:
            needs_2h = True
        
        result.append({
            "appointment_id": appt.id,
            "doctor_name": appt.doctor.user.full_name if appt.doctor.user else "Unknown",
            "hospital_name": appt.hospital.name if appt.hospital else "Unknown",
            "scheduled_start": appt.scheduled_start.isoformat(),
            "needs_24h_reminder": needs_24h,
            "needs_2h_reminder": needs_2h,
        })
    
    return ok(data={"upcoming_appointments": result})