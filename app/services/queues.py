"""Queue management service with emergency/priority queue support."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from app.errors import AppError
from app.extensions import db
from app.models import (
    Appointment,
    AppointmentStatus,
    Queue,
    QueueStatus,
    QueueToken,
    User,
    utcnow,
)
from app.services.audit import log_action
from app.services.sse import sse_broker
from app.services.push_notifications import send_push_notification
from app.utils.responses import ok


def get_or_create_queue(hospital_id: int, doctor_id: int | None, department_id: int | None, queue_date: date):
    queue = Queue.query.filter_by(hospital_id=hospital_id, doctor_id=doctor_id, queue_date=queue_date).first()
    if not queue:
        queue = Queue(hospital_id=hospital_id, doctor_id=doctor_id, department_id=department_id, queue_date=queue_date, prefix="A")
        db.session.add(queue)
        db.session.flush()
    return queue


def check_in(actor: User, appointment: Appointment, priority: int = 3) -> QueueToken:
    """Check in a patient with optional emergency/priority queue support.
    
    Args:
        actor: The user performing the check-in
        appointment: The appointment to check in
        priority: 1=emergency, 2=priority, 3=standard (default)
    """
    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment cannot be checked in", 400, "invalid_status")

    # Check if token already exists
    if QueueToken.query.filter_by(appointment_id=appointment.id).first():
        raise AppError("Token already generated", 409, "token_exists")

    queue = get_or_create_queue(appointment.hospital_id, appointment.doctor_id, appointment.department_id, appointment.scheduled_start.date())

    # Determine position based on priority
    # Emergency/priority tokens get placed at the front
    position = _calculate_priority_position(queue, priority)

    # Mark appointment as checked in
    appointment.status = AppointmentStatus.CHECKED_IN
    appointment.actual_start_time = utcnow()

    token = QueueToken(
        queue_id=queue.id,
        appointment_id=appointment.id,
        token_number=f"{queue.prefix}-{position:03d}",
        position=position,
        status=QueueStatus.WAITING,
        priority_level=priority,
        checked_in_at=utcnow(),
    )
    db.session.add(token)
    db.session.flush()

    # Calculate waiting time estimate
    wait_estimate = calculate_waiting_time(appointment, queue, token)

    # Notify patient
    patient = appointment.patient
    if patient and patient.user:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka"))
        scheduled = appointment.scheduled_start.astimezone(local_tz)
        now_local = datetime.now(local_tz)

        # Build priority label
        priority_labels = {1: "Emergency", 2: "Priority", 3: "Standard"}
        priority_label = priority_labels.get(priority, "Standard")

        # Determine how far along we are
        time_until_scheduled = (scheduled - now_local).total_seconds() / 60
        estimated_wait = wait_estimate if wait_estimate else 0

        # Emergency patients get immediate attention
        if priority == 1:
            message = f"🚨 Emergency token generated: {token.token_number}. You are being seen immediately. Priority level: {priority_label}."
        elif priority == 2:
            message = f"📋 Priority token generated: {token.token_number}. Estimated wait: {estimated_wait} minutes. Priority level: {priority_label}."
        else:
            message = f"Your token is {token_number}. Estimated wait time: {estimated_wait} minutes. Priority level: {priority_label}. Appointment at {scheduled.strftime('%I:%M %p')}."
        notify(patient.user_id, "token_generated", "Queue token generated", message, {"token_id": token.id, "appointment_id": appointment.id, "priority_level": priority})

    # Audit log
    log_action(actor, "queue.token_generated", "QueueToken", token.id, after=token.to_dict())

    # Publish SSE update with priority info
    priority_icons = {1: "🚨", 2: "⚠️", 3: "📋"}
    sse_broker.publish(appointment.hospital_id, "queue_update", {
        "action": "check_in", 
        "token_number": token.token_number, 
        "priority_level": priority,
        "priority_icon": priority_icons.get(priority, "📋"),
        "wait_estimate": wait_estimate
    })

    return token


def _calculate_priority_position(queue: Queue, priority: int) -> int:
    """Calculate position in queue based on priority level.
    
    Priority 1 (Emergency) gets position 1 (front of queue)
    Priority 2 (Priority) gets position after standard tokens at same position
    Priority 3 (Standard) gets normal position
    """
    # Count existing standard tokens (priority_level=3)
    standard_count = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING, priority_level=3).count()
    # Count existing priority tokens (priority_level=2)
    priority_count = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING, priority_level=2).count()
    # Count existing emergency tokens (priority_level=1)
    emergency_count = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING, priority_level=1).count()
    
    if priority == 1:
        # Emergency gets position 1 (front of queue)
        return 1
    elif priority == 2:
        # Priority gets position after all emergencies but before standards
        return emergency_count + 1
    else:
        # Standard gets position after all emergencies and priorities
        return emergency_count + priority_count + 1


def call_next(actor: User, queue: Queue) -> QueueToken:
    """Call the next token with emergency/priority precedence."""
    # Find the highest priority token first
    emergency_token = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING, priority_level=1).order_by(QueueToken.position.asc()).first()
    priority_token = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING, priority_level=2).order_by(QueueToken.position.asc()).first()
    standard_token = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING, priority_level=3).order_by(QueueToken.position.asc()).first()
    
    # Select in order: Emergency > Priority > Standard
    token = emergency_token or priority_token or standard_token
    
    if not token:
        raise AppError("No waiting patient", 404, "queue_empty")

    # Mark token as called
    token.status = QueueStatus.CALLED
    token.called_at = utcnow()

    # Update appointment status
    token.appointment.status = AppointmentStatus.WAITING

    # Calculate actual wait time
    if token.checked_in_at:
        actual_wait = (utcnow() - token.checked_in_at).total_seconds() / 60
    else:
        actual_wait = 0

    # Update the token with actual wait time
    token.wait_actual_minutes = int(actual_wait)

    # Get next token (next in same priority level)
    next_up = QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING).order_by(QueueToken.position.asc()).first()

    # Get doctor info
    doctor = token.appointment.doctor
    branch = next((a for a in doctor.hospital_assignments if a.hospital_id == queue.hospital_id), None)

    # Prepare SSE payload with priority info
    priority_icons = {1: "🚨", 2: "⚠️", 3: "📋"}
    priority_labels = {1: "Emergency", 2: "Priority", 3: "Standard"}
    
    payload = {
        "current_token": {
            "token_number": token.token_number,
            "priority_level": token.priority_level,
            "priority_label": priority_labels.get(token.priority_level, "Standard"),
            "wait_actual_minutes": token.wait_actual_minutes,
            "wait_estimate_minutes": token.wait_estimate_minutes,
        },
        "next_token": {
            "token_number": next_up.token_number if next_up else None,
            "priority_level": next_up.priority_level if next_up else None,
            "priority_label": priority_labels.get(next_up.priority_level, "Standard") if next_up else None,
        } if next_up else None,
        "doctor": doctor.user.full_name if doctor.user else "Unknown",
        "room": branch.room if branch else None,
        "wait_time_estimate": get_queue_wait_estimate(queue.hospital_id),
        "priority_announcement": f"{priority_labels.get(token.priority_level, 'Standard')} token {token.token_number} is now being called!",
    }

    # Publish SSE update
    sse_broker.publish(queue.hospital_id, "queue_update", payload)

    # Notify patient
    if token.appointment.patient and token.appointment.patient.user:
        priority_labels = {1: "🚨 Emergency", 2: "⚠️ Priority", 3: "📋 Standard"}
        notify(
            token.appointment.patient.user_id,
            "token_called",
            "Token called",
            f"{priority_labels.get(token.priority_level, 'Standard')} token {token.token_number} has been called. Actual wait: {token.wait_actual_minutes} min",
            {"token_id": token.id, "priority_level": token.priority_level},
        )

    log_action(actor, "queue.called_next", "QueueToken", token.id, after=token.to_dict())

    return token


def update_token_status(actor: User, token: QueueToken, status: QueueStatus):
    """Update token status with emergency/priority support."""
    token.status = status

    if status == QueueStatus.IN_CONSULTATION:
        token.appointment.status = AppointmentStatus.IN_CONSULTATION
        # Record actual start time if not already set
        if not token.appointment.actual_start_time:
            token.appointment.actual_start_time = utcnow()

        notify(
            token.appointment.patient.user_id,
            "consultation_started",
            "Consultation starting",
            f"Your token {token.token_number} is now with {token.appointment.doctor.user.full_name}.",
            {"token_id": token.id},
        )
    elif status == QueueStatus.COMPLETED:
        token.appointment.status = AppointmentStatus.COMPLETED
        token.completed_at = utcnow()

        # Notify patient
        notify(
            token.appointment.patient.user_id,
            "appointment_completed",
            "Appointment completed",
            f"Your appointment with {token.appointment.doctor.user.full_name} has been completed.",
            {"token_id": token.id},
        )
    elif status == QueueStatus.CANCELLED:
        token.appointment.status = AppointmentStatus.CANCELLED

    # Update SSE with new status
    sse_broker.publish(token.queue.hospital_id, "queue_update", {"action": "status_update", "token_id": token.id, "status": token.status.value, "priority_level": token.priority_level})

    log_action(actor, "queue.status_updated", "QueueToken", token.id, after=token.to_dict())
    return token


def calculate_waiting_time(appointment: Appointment, queue: Queue, token: QueueToken) -> int:
    """Calculate estimated waiting time in minutes based on historical data and priority."""
    from app.models import QueueToken as QT

    try:
        # Factor 1: Doctor's historical average delay
        past_appointments = Appointment.query.filter(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.hospital_id == appointment.hospital_id,
            Appointment.actual_start_time.isnot(None),
            Appointment.status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW]),
        ).all()

        if past_appointments:
            total_delay = 0
            count = 0
            for past_appt in past_appointments:
                delay = (past_appt.actual_start_time - past_appt.scheduled_start).total_seconds() / 60
                if abs(delay) < 180:  # Ignore extreme outliers (>3 min)
                    total_delay += delay
                    count += 1

            avg_doctor_delay = total_delay / count if count > 0 else 0
        else:
            avg_doctor_delay = 0

        # Factor 2: Current queue position considering priority
        # Count tokens ahead with same or lower priority
        tokens_ahead = QueueToken.query.filter(
            QueueToken.queue_id == queue.id,
            QueueToken.status == QueueStatus.WAITING,
            QueueToken.priority_level >= token.priority_level,
            QueueToken.position < token.position,
        ).count()

        # Base wait per position (average consultation time ~15 min)
        wait_per_position = 15

        # Factor 3: Time of day pattern
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(current_app.config.get("BUSINESS_TIMEZONE", "Asia/Dhaka"))
        tz = ZoneInfo(local_tz)
        scheduled = appointment.scheduled_start
        start_local = scheduled.astimezone(tz)
        hour = start_local.hour

        # Peak hours: 9 AM - 11 AM and 2 PM - 4 PM
        if 9 <= hour <= 11 or 14 <= hour <= 16:
            peak_factor = 1.5
        else:
            peak_factor = 1.0

        # Factor 4: Appointment type
        wait_type_factor = 1.0
        if appointment.appointment_type == "follow_up":
            wait_type_factor = 0.7
        elif appointment.appointment_type == "first_visit":
            wait_type_factor = 1.3

        # Calculate total estimate with priority adjustment
        # Emergency/priority tokens have reduced wait due to front-of-queue positioning
        priority_reduction = {1: 0, 2: tokens_ahead * wait_per_position * 0.3, 3: 0}.get(token.priority_level, 0)
        
        position_wait = tokens_ahead * wait_per_position * wait_type_factor
        doctor_delay_factor = abs(avg_doctor_delay) * 0.5
        peak_adjustment = position_wait * (peak_factor - 1) if 'peak_factor' in dir() else 0

        total_estimate = int(position_wait + doctor_delay_factor + peak_adjustment - priority_reduction)

        # Ensure minimum wait of 5 minutes and reasonable maximum
        return max(5, min(total_estimate, 120))

    except Exception as e:
        current_app.logger.error(f"Error calculating waiting time: {e}")
        return 10


def get_queue_wait_estimate(hospital_id: int) -> int:
    """Get overall queue wait estimate for a hospital (for dashboard display)."""
    from app.models import QueueToken as QT

    completed_tokens = QueueToken.query.filter(
        QueueToken.status == QueueStatus.COMPLETED,
        QueueToken.completed_at.isnot(None),
    ).all()

    if not completed_tokens:
        return 15

    total_wait = 0
    count = 0
    for token in completed_tokens:
        if token.checked_in_at and token.appointment.actual_start_time:
            wait = (token.appointment.actual_start_time - token.checked_in_at).total_seconds() / 60
            if 5 <= wait <= 180:
                total_wait += wait
                count += 1

    if count > 0:
        return int(total_wait / count)
    return 15


def get_patient_position(queue_id: int, patient_id: int) -> dict:
    """Get patient's position in queue with wait estimate and priority info."""
    from app.models import Appointment

    queue = db.session.get(Queue, queue_id)
    if not queue:
        return {"position": None, "wait_estimate": 15, "total_waiting": 0, "priority_level": 3}

    # Find the patient's appointment within this hospital's queue
    appointment = (
        Appointment.query.filter_by(patient_id=patient_id, hospital_id=queue.hospital_id)
        .first()
    )
    if not appointment:
        return {"position": None, "wait_estimate": 15, "total_waiting": 0, "priority_level": 3}

    # Find the patient's token in this queue
    token = QueueToken.query.filter_by(queue_id=queue.id, appointment_id=appointment.id).first()
    if not token:
        return {"position": None, "wait_estimate": 15, "total_waiting": 0, "priority_level": 3}

    # Count tokens ahead with same or lower priority
    tokens_ahead = QueueToken.query.filter(
        QueueToken.queue_id == queue.id,
        QueueToken.status == QueueStatus.WAITING,
        QueueToken.priority_level >= token.priority_level,
        QueueToken.position < token.position,
    ).count()

    # Get wait estimate
    wait_estimate = calculate_waiting_time(appointment, queue, token)

    return {
        "position": token.position,
        "wait_estimate": wait_estimate,
        "tokens_ahead": tokens_ahead,
        "total_waiting": QueueToken.query.filter_by(queue_id=queue.id, status=QueueStatus.WAITING).count(),
        "priority_level": token.priority_level,
        "priority_label": {1: "Emergency", 2: "Priority", 3: "Standard"}.get(token.priority_level, "Standard"),
    }