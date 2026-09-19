from __future__ import annotations

from flask import Blueprint, Response, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Queue, QueueToken, User
from app.security import current_user, hospital_ids_for_user
from app.services.queues import call_next, update_token_status
from app.services.sse import sse_broker
from app.utils.responses import ok

bp = Blueprint("queues", __name__, url_prefix="/api")


@bp.get("/queues/display")
def queue_display():
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "validation_error")
    from datetime import date
    from app.models import QueueToken as QT
    from app.models import QueueStatus

    q = Queue.query.filter_by(hospital_id=hospital_id, queue_date=date.today()).first()
    if not q or not q.current_token_id:
        return ok({"hospital_id": hospital_id, "current_token": None, "next_token": None, "doctor": None, "room": None})
    current = db.session.get(QueueToken, q.current_token_id)
    next_token = QueueToken.query.filter_by(queue_id=q.id, status=QueueStatus.WAITING).order_by(QueueToken.position.asc()).first()
    doctor = current.appointment.doctor
    branch = next((a for a in doctor.hospital_assignments if a.hospital_id == hospital_id), None)
    return ok({
        "hospital_id": hospital_id,
        "current_token": current.to_dict(),
        "next_token": next_token.to_dict() if next_token else None,
        "doctor": doctor.user.full_name,
        "room": branch.room if branch else None,
    })


@bp.get("/queues/stream")
def queue_stream():
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "validation_error")

    def stream():
        q = sse_broker.subscribe(hospital_id)
        try:
            while True:
                yield q.get()
        except GeneratorExit:
            sse_broker.unsubscribe(hospital_id, q)

    return Response(stream(), mimetype="text/event-stream")


@bp.post("/queues/<int:queue_id>/call-next")
@jwt_required()
def call_next_route(queue_id):
    user = current_user()
    queue = db.session.get(Queue, queue_id)
    if not queue:
        raise AppError("Queue not found", 404, "not_found")
    token = call_next(user, queue)
    db.session.commit()
    return ok(token.to_dict())


@bp.post("/tokens/<int:token_id>/status")
@jwt_required()
def token_status(token_id):
    user = current_user()
    token = db.session.get(QueueToken, token_id)
    if not token:
        raise AppError("Token not found", 404, "not_found")
    data = request.get_json(silent=True) or {}
    from app.models import QueueStatus
    status = data.get("status")
    if status not in {s.value for s in QueueStatus}:
        raise AppError("Invalid status", 400, "validation_error")
    update_token_status(user, token, QueueStatus(status))
    db.session.commit()
    return ok(token.to_dict())