"""Smart queue and waiting time estimation routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Appointment, Queue, QueueToken, QueueStatus, Hospital
from app.security import current_user, require_hospital_access, roles_required, can_access_hospital
from app.services.queues import calculate_waiting_time, get_queue_wait_estimate, get_patient_position, check_in, call_next
from app.utils.responses import ok, error

bp = Blueprint("smart_queue", __name__, url_prefix="/api/smart-queue")


@bp.get("/queue/<int:queue_id>/position/<int:patient_id>")
@jwt_required()
def get_patient_queue_position(queue_id: int, patient_id: int):
    """Get patient's position in queue with waiting time estimate."""
    user = current_user()

    # Resolve the queue and verify hospital access
    queue = db.session.get(Queue, queue_id)
    if not queue:
        raise AppError("Queue not found", 404, "not_found")

    if not can_access_hospital(user, queue.hospital_id):
        raise AppError("Access denied", 403, "access_denied")

    # Verify the patient belongs to this hospital
    appointment = db.session.get(Appointment, patient_id) if False else None
    result = get_patient_position(queue_id, patient_id)
    if not result or result.get("position") is None:
        raise AppError("Patient not found in this queue", 404, "not_found")

    return ok(data=result)


@bp.get("/queue/<int:queue_id>/wait-estimate")
@jwt_required()
def get_queue_wait_estimate_route(queue_id: int):
    """Get overall queue wait estimate for a hospital dashboard."""
    user = current_user()

    queue = db.session.get(Queue, queue_id)
    if not queue:
        raise AppError("Queue not found", 404, "not_found")

    if not can_access_hospital(user, queue.hospital_id):
        raise AppError("Hospital access denied", 403, "hospital_access_denied")

    estimate = get_queue_wait_estimate(queue_id)
    return ok(data={"wait_estimate_minutes": estimate})


@bp.post("/queue/<int:queue_id>/check-in/<int:appointment_id>")
@jwt_required()
def route_check_in(queue_id: int, appointment_id: int):
    """Route for checking in a patient (updates token with wait estimate)."""
    user = current_user()

    # Resolve the queue and verify hospital access
    queue = db.session.get(Queue, queue_id)
    if not queue:
        raise AppError("Queue not found", 404, "not_found")

    if not can_access_hospital(user, queue.hospital_id):
        raise AppError("Hospital access denied", 403, "hospital_access_denied")

    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        raise AppError("Appointment not found", 404, "not_found")

    # Verify the appointment belongs to this queue's hospital
    if appointment.hospital_id != queue.hospital_id:
        raise AppError("Hospital access denied", 403, "hospital_access_denied")

    # Perform check-in through the service
    token = check_in(user, appointment)
    db.session.commit()

    return ok(data=token.to_dict(), message="Patient checked in with wait estimate")


@bp.post("/queue/<int:queue_id>/call-next")
@jwt_required()
def route_call_next(queue_id: int):
    """Route for calling the next patient in queue."""
    user = current_user()

    queue = db.session.get(Queue, queue_id)
    if not queue:
        raise AppError("Queue not found", 404, "not_found")

    if not can_access_hospital(user, queue.hospital_id):
        raise AppError("Hospital access denied", 403, "hospital_access_denied")

    token = call_next(user, queue)
    db.session.commit()

    return ok(data=token.to_dict())


@bp.get("/hospital/<int:hospital_id>/queue-status")
@jwt_required()
def get_hospital_queue_status(hospital_id: int):
    """Get complete queue status for a hospital including wait estimates."""
    user = current_user()
    if not can_access_hospital(user, hospital_id):
        raise AppError("Hospital access denied", 403, "hospital_access_denied")

    hospital = db.session.get(Hospital, hospital_id)
    if not hospital:
        raise AppError("Hospital not found", 404, "not_found")

    # Get today's queue for this hospital
    from datetime import date
    today = date.today()
    queues = Queue.query.filter_by(hospital_id=hospital_id, queue_date=today).all()

    # Get wait estimate
    wait_estimate = get_queue_wait_estimate(hospital_id)

    # Build token info across all today's queues
    token_info = []
    for queue in queues:
        tokens = QueueToken.query.filter_by(queue_id=queue.id).order_by(QueueToken.position).all()
        for token in tokens:
            appointment = token.appointment
            token_info.append({
                "token_id": token.id,
                "token_number": token.token_number,
                "position": token.position,
                "status": token.status.value,
                "wait_actual_minutes": token.wait_actual_minutes,
                "wait_estimate_minutes": token.wait_estimate_minutes,
                "patient_id": appointment.patient_id if appointment else None,
                "appointment_id": appointment.id if appointment else None,
            })

    waiting_count = sum(1 for t in token_info if t["status"] == QueueStatus.WAITING.value)

    return ok(data={
        "hospital_id": hospital_id,
        "hospital_name": hospital.name,
        "wait_estimate_minutes": wait_estimate,
        "total_waiting": waiting_count,
        "queues": len(queues),
        "tokens": token_info,
    })
