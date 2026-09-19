"""Follow-up and reminder system for appointments and consultations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from flask import current_app

from app.extensions import db
from app.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    Patient,
    PushNotificationLog,
    User,
    DeviceToken,
    DevicePlatform,
)
from app.services.push_notifications import (
    send_push_notification,
    get_user_devices,
    _is_quiet_hours,
    DevicePlatform,
)
from app.services.audit import log_action
from app.services.notifications import notify


# ─── Reminder Timing ──────────────────────────────────────────────────────────

# Standard reminder timing offsets
REMINDER_24H_OFFSET = timedelta(hours=24)
REMINDER_2H_OFFSET = timedelta(hours=2)


def get_reminder_times(scheduled_start: datetime) -> dict:
    """Calculate the two standard reminder times for an appointment.
    
    Returns:
        dict with 'reminder_24h' and 'reminder_2h' as datetime objects
        in the business timezone, and UTC equivalents.
    """
    local_tz = current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka")
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(local_tz)
    
    start_local = scheduled_start.astimezone(tz)
    
    # 24 hours before
    reminder_24h_local = start_local - REMINDER_24H_OFFSET
    reminder_24h_utc = reminder_24h_local.astimezone(timezone.utc)
    
    # 2 hours before
    reminder_2h_local = start_local - REMINDER_2H_OFFSET
    reminder_2h_utc = reminder_2h_local.astimezone(timezone.utc)
    
    return {
        "reminder_24h": {
            "local": reminder_24h_local,
            "utc": reminder_24h_utc,
        },
        "reminder_2h": {
            "local": reminder_2h_local,
            "utc": reminder_2h_utc,
        },
    }


# ─── Check for Appointments Needing Reminders ───────────────────────────────


def get_appointments_needing_reminder(
    reminder_type: str = "24h",
    hospital_id: Optional[int] = None,
) -> List[Appointment]:
    """Get appointments that need reminders sent.
    
    Args:
        reminder_type: "24h" or "2h" indicating which reminder window
        hospital_id: Optional hospital filter
    
    Returns:
        List of appointments scheduled for reminder within the next hour
    """
    now = datetime.now(timezone.utc)
    local_tz = current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka")
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(local_tz)
    
    # Calculate the target time window
    if reminder_type == "24h":
        # Appointments scheduled for reminder_24h time have already passed
        # We want appointments where current time is before reminder_24h but approaching
        target_time = now + REMINDER_24H_OFFSET
    else:  # "2h"
        target_time = now + REMINDER_2H_OFFSET
    
    # Query appointments scheduled between now and target_time
    # plus a small buffer for timing precision
    buffer = timedelta(minutes=30)
    window_end = target_time + buffer
    
    query = Appointment.query.filter(
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.scheduled_start > now,
        Appointment.scheduled_start <= window_end,
    )
    
    if hospital_id:
        from app.security import can_access_hospital
        # This is a simplification - in production, check user's hospital access
        query = query.filter(Appointment.hospital_id == hospital_id)
    
    appointments = query.order_by(Appointment.scheduled_start.asc()).all()
    
    # Filter to only those needing the specific reminder type
    result = []
    for appt in appointments:
        times = get_reminder_times(appt.scheduled_start)
        if reminder_type == "24h":
            # Reminder should have been sent 24h before, so check if we're in the window
            # (between 24h and 25h before the appointment)
            twenty_four_h_before = appt.scheduled_start - REMINDER_24H_OFFSET
            twenty_five_h_before = appt.scheduled_start - timedelta(hours=25)
            if twenty_five_h_before <= now <= twenty_four_h_before:
                result.append(appt)
        else:  # "2h"
            # Check if we're in the 2h window
            two_h_before = appt.scheduled_start - REMINDER_2H_OFFSET
            two_point_five_h_before = appt.scheduled_start - timedelta(hours=2.5)
            if two_h_before <= now <= two_point_five_h_before:
                result.append(appt)
    
    return result


# ─── Send Reminder Notifications ─────────────────────────────────────────────


def send_appointment_reminder(
    appointment: Appointment,
    reminder_type: str = "24h",
    force: bool = False,
) -> List[PushNotificationLog]:
    """Send a reminder notification for an appointment.
    
    Args:
        appointment: The appointment to remind about
        reminder_type: "24h" or "2h" indicating which reminder
        force: If True, send even if reminder already sent
    
    Returns:
        List of PushNotificationLog entries
    """
    patient = appointment.patient
    if not patient or not patient.user:
        logger = current_app.logger
        logger.warning(f"Appointment {appointment.id} has no patient/user associated")
        return []
    
    user = patient.user
    
    # Check if patient has devices
    devices = get_user_devices(user.id, appointment.hospital_id)
    if not devices:
        # Fall back to in-app notification
        return _send_in_app_reminder(appointment, reminder_type)
    
    # Determine reminder message based on type
    if reminder_type == "24h":
        title = "Appointment Reminder - 24 Hours"
        body = f"Your appointment with Dr. {appointment.doctor.user.full_name} at {appointment.hospital.name} is scheduled for {appointment.scheduled_start.strftime('%d %b %Y, %I:%M %p')}. Please arrive 15 minutes early."
    else:  # "2h"
        title = "Appointment Reminder - 2 Hours"
        body = f"Your appointment is in 2 hours with Dr. {appointment.doctor.user.full_name} at {appointment.hospital.name}. Please proceed to the reception desk."
    
    # Send push notifications to all devices
    logs = send_push_notification(
        user_id=user.id,
        title=title,
        body=body,
        data={
            "appointment_id": appointment.id,
            "reminder_type": reminder_type,
            "patient_id": patient.id,
        },
        hospital_id=appointment.hospital_id,
    )
    
    # If no push devices, fall back to in-app
    if not logs or all(l.status == "failed" for l in logs):
        return _send_in_app_reminder(appointment, reminder_type)
    
    # Audit log
    log_action(
        user=user,
        action=f"appointment_reminder_{reminder_type}sent",
        entity="appointment",
        entity_id=appointment.id,
        after={"reminder_type": reminder_type, "patient_id": patient.id},
    )
    
    return logs


def _send_in_app_reminder(appointment: Appointment, reminder_type: str) -> List[PushNotificationLog]:
    """Send in-app reminder when no push devices are available."""
    from app.models import Notification
    
    # Determine message
    if reminder_type == "24h":
        title = "Appointment Reminder - 24 Hours"
        body = f"Your appointment with Dr. {appointment.doctor.user.full_name} at {appointment.hospital.name} is scheduled for {appointment.scheduled_start.strftime('%d %b %Y, %I:%M %p')}."
    else:
        title = "Appointment Reminder - 2 Hours"
        body = f"Your appointment is in 2 hours with Dr. {appointment.doctor.user.full_name}."
    
    # Create in-app notification
    notification = notify(
        user_id=appointment.patient.user_id,
        event_type="appointment_reminder",
        title=title,
        body=body,
    )
    
    # Log the notification
    from app.models import PushNotificationLog
    log = PushNotificationLog(
        device_token_id=None,  # In-app notification
        notification_id=notification.id,
        title=title,
        body=body,
        status="sent",
        sent_at=datetime.now(timezone.utc),
    )
    db.session.add(log)
    
    return [log]


# ─── Send Follow-up Consultation Reminder ───────────────────────────────────


def send_follow_up_reminder(consultation: Consultation) -> List[PushNotificationLog]:
    """Send a follow-up consultation reminder if a follow-up date is set."""
    if not consultation.follow_up_date:
        return []
    
    from datetime import date
    today = datetime.now(timezone.utc).date()
    
    # Send reminder 1 day before follow-up
    follow_up_date = consultation.follow_up_date
    if follow_up_date <= today:
        return []  # Follow-up date already passed
    
    days_until = (follow_up_date - today).days
    if days_until > 1:
        return []  # Too far in the future
    
    patient = consultation.patient
    if not patient or not patient.user:
        return []
    
    user = patient.user
    
    # Determine message based on days until follow-up
    if days_until == 1:
        title = "Follow-up Consultation Tomorrow"
        body = f"Your follow-up consultation scheduled for tomorrow (date: {follow_up_date.strftime('%d %b %Y')}) with Dr. {consultation.doctor.user.full_name if consultation.doctor else 'your doctor'}. Please confirm your attendance."
    else:  # days_until == 0 (today)
        title = "Follow-up Consultation Today"
        body = f"Your follow-up consultation is scheduled for today (date: {follow_up_date.strftime('%d %b %Y')}) with Dr. {consultation.doctor.user.full_name if consultation.doctor else 'your doctor'}. Please proceed to the clinic."
    
    # Send push notification
    devices = get_user_devices(user.id, consultation.hospital_id)
    
    if devices:
        logs = send_push_notification(
            user_id=user.id,
            title=title,
            body=body,
            data={
                "consultation_id": consultation.id,
                "follow_up": True,
                "patient_id": patient.id,
            },
            hospital_id=consultation.hospital_id,
        )
    else:
        logs = _send_in_app_follow_up_reminder(consultation, title, body)
    
    # Audit log
    log_action(
        user=user,
        action="follow_up_reminder_sent",
        entity="consultation",
        entity_id=consultation.id,
        after={"follow_up_date": str(consultation.follow_up_date), "patient_id": patient.id},
    )
    
    return logs


def _send_in_app_follow_up_reminder(consultation: Consultation, title: str, body: str) -> List[PushNotificationLog]:
    """Send in-app follow-up reminder when no push devices."""
    from app.models import Notification, PushNotificationLog
    
    notification = notify(
        user_id=consultation.patient.user_id,
        event_type="follow_up_reminder",
        title=title,
        body=body,
    )
    
    log = PushNotificationLog(
        device_token_id=None,
        notification_id=notification.id,
        title=title,
        body=body,
        status="sent",
        sent_at=datetime.now(timezone.utc),
    )
    db.session.add(log)
    
    return [log]


# ─── Scheduler Integration ───────────────────────────────────────────────────


def check_and_send_reminders(hospital_id: Optional[int] = None) -> dict:
    """Check for appointments due for reminders and send them.
    
    This is designed to be called by a cron job or scheduler.
    Typically run every 30 minutes.
    
    Returns:
        dict with counts of reminders sent
    """
    sent_24h = 0
    sent_2h = 0
    sent_follow_up = 0
    errors = 0
    
    # Get appointments needing 24h reminders
    appointments_24h = get_appointments_needing_reminder("24h", hospital_id)
    for appt in appointments_24h:
        try:
            logs = send_appointment_reminder(appt, "24h")
            sent_24h += len([l for l in logs if l.status in ["sent", "logged"]])
        except Exception as e:
            current_app.logger.error(f"Error sending 24h reminder for appt {appt.id}: {e}")
            errors += 1
    
    # Get appointments needing 2h reminders
    appointments_2h = get_appointments_needing_reminder("2h", hospital_id)
    for appt in appointments_2h:
        try:
            logs = send_appointment_reminder(appt, "2h")
            sent_2h += len([l for l in logs if l.status in ["sent", "logged"]])
        except Exception as e:
            current_app.logger.error(f"Error sending 2h reminder for appt {appt.id}: {e}")
            errors += 1
    
    # Check for follow-up reminders
    from app.models import Consultation
    # A consultation is considered "completed" if it has a completed_at date
    query = Consultation.query.filter(
        Consultation.follow_up_date.isnot(None),
        Consultation.completed_at.isnot(None),
    )
    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)
    
    follow_ups = query.limit(50).all()  # Limit to prevent timeout
    for consult in follow_ups:
        try:
            logs = send_follow_up_reminder(consult)
            sent_follow_up += len(logs)
        except Exception as e:
            current_app.logger.error(f"Error sending follow-up reminder for consult {consult.id}: {e}")
            errors += 1
    
    return {
        "sent_24h": sent_24h,
        "sent_2h": sent_2h,
        "sent_follow_up": sent_follow_up,
        "errors": errors,
    }