from datetime import datetime, timezone
import uuid
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from ..errors import AppError
from ..extensions import db
from ..models import (
    Invoice,
    InvoiceItem,
    Payment,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
    Appointment,
    Doctor,
    Patient,
    Hospital,
    Role,
)
from ..security import current_user, require_hospital_access, get_current_tenant


bp = Blueprint("billing", __name__, url_prefix="/api/billing")


def generate_invoice_number(hospital_id: int) -> str:
    now = datetime.now(timezone.utc)
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"INV-{now.strftime('%Y%m')}-H{hospital_id}-{short_uuid}"


def generate_payment_number(hospital_id: int) -> str:
    now = datetime.now(timezone.utc)
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"PAY-{now.strftime('%Y%m')}-H{hospital_id}-{short_uuid}"


@bp.route("/invoices", methods=["GET"])
@jwt_required()
def list_invoices():
    """List invoices with filtering."""
    user = current_user()
    tenant = get_current_tenant()

    query = Invoice.query.filter(Invoice.deleted_at.is_(None))

    if user.role == Role.PATIENT:
        if not user.patient_profile:
            return jsonify({"data": {"invoices": []}})
        query = query.filter_by(patient_id=user.patient_profile.id)
    elif user.role in [Role.ADMIN, Role.RECEPTIONIST, Role.DOCTOR]:
        if tenant:
            require_hospital_access(user, tenant.id)
            query = query.filter_by(hospital_id=tenant.id)
        else:
            hospital_id = request.args.get("hospital_id", type=int)
            if hospital_id:
                require_hospital_access(user, hospital_id)
                query = query.filter_by(hospital_id=hospital_id)
            elif user.role == Role.DOCTOR and user.doctor_profile:
                # Doctor can see invoices linked to their appointments
                query = query.join(Appointment, Invoice.appointment_id == Appointment.id)\
                             .filter(Appointment.doctor_id == user.doctor_profile.id)
    elif user.role == Role.SUPER_ADMIN:
        hospital_id = request.args.get("hospital_id", type=int)
        if hospital_id:
            query = query.filter_by(hospital_id=hospital_id)

    # Filters
    status = request.args.get("status")
    if status:
        query = query.filter(Invoice.status == status)

    patient_id = request.args.get("patient_id", type=int)
    if patient_id and user.role != Role.PATIENT:
        query = query.filter(Invoice.patient_id == patient_id)

    invoices = query.order_by(Invoice.created_at.desc()).all()
    return jsonify({
        "data": {
            "invoices": [inv.to_dict() for inv in invoices]
        }
    })


@bp.route("/invoices/<int:invoice_id>", methods=["GET"])
@jwt_required()
def get_invoice(invoice_id):
    """Get full invoice details with items and payment history."""
    user = current_user()
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.deleted_at is not None:
        raise AppError("Invoice not found", 404, "not_found")

    if user.role == Role.PATIENT:
        if not user.patient_profile or invoice.patient_id != user.patient_profile.id:
            raise AppError("Access denied", 403, "access_denied")
    elif user.role in [Role.ADMIN, Role.RECEPTIONIST, Role.DOCTOR]:
        require_hospital_access(user, invoice.hospital_id)

    inv_data = invoice.to_dict()
    inv_data["hospital_name"] = invoice.hospital.name if invoice.hospital else None
    inv_data["hospital_address"] = invoice.hospital.address if invoice.hospital else None
    inv_data["hospital_phone"] = invoice.hospital.phone if invoice.hospital else None
    inv_data["patient_phone"] = invoice.patient.user.phone if invoice.patient and invoice.patient.user else None
    inv_data["patient_email"] = invoice.patient.user.email if invoice.patient and invoice.patient.user else None
    inv_data["items"] = [item.to_dict() for item in invoice.items]
    inv_data["payments"] = [p.to_dict() for p in invoice.payments]

    return jsonify({"data": {"invoice": inv_data}})


@bp.route("/invoices", methods=["POST"])
@jwt_required()
def create_invoice():
    """Create a new manual/itemized invoice."""
    user = current_user()
    if user.role not in [Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST]:
        raise AppError("Only hospital staff can create invoices", 403, "permission_denied")

    data = request.get_json() or {}
    patient_id = data.get("patient_id")
    hospital_id = data.get("hospital_id")
    items_data = data.get("items", [])
    discount_amount = float(data.get("discount_amount", 0))
    tax_amount = float(data.get("tax_amount", 0))
    notes = data.get("notes", "").strip()
    appointment_id = data.get("appointment_id")

    if not patient_id or not hospital_id or not items_data:
        raise AppError("patient_id, hospital_id, and at least one item are required", 400, "validation_error")

    require_hospital_access(user, hospital_id)

    patient = db.session.get(Patient, patient_id)
    if not patient:
        raise AppError("Patient not found", 404, "patient_not_found")

    # Calculate item totals
    total_amount = 0.0
    invoice_items = []
    for it in items_data:
        desc = it.get("description", "").strip()
        itype = it.get("item_type", "consultation")
        qty = int(it.get("quantity", 1))
        unit_p = float(it.get("unit_price", 0))
        if not desc or qty <= 0 or unit_p < 0:
            raise AppError("Invalid item data", 400, "invalid_item")
        total_p = qty * unit_p
        total_amount += total_p
        invoice_items.append(InvoiceItem(
            item_type=itype,
            description=desc,
            quantity=qty,
            unit_price=unit_p,
            total_price=total_p,
            related_id=it.get("related_id")
        ))

    payable = max(0.0, total_amount + tax_amount - discount_amount)
    inv_number = generate_invoice_number(hospital_id)

    invoice = Invoice(
        invoice_number=inv_number,
        patient_id=patient_id,
        hospital_id=hospital_id,
        appointment_id=appointment_id,
        total_amount=total_amount,
        discount_amount=discount_amount,
        tax_amount=tax_amount,
        payable_amount=payable,
        paid_amount=0,
        due_amount=payable,
        status=InvoiceStatus.PENDING.value,
        notes=notes,
        created_by_user_id=user.id
    )
    invoice.items = invoice_items

    db.session.add(invoice)
    db.session.commit()

    return jsonify({"data": {"invoice": invoice.to_dict()}}), 201


@bp.route("/invoices/auto-from-appointment/<int:appointment_id>", methods=["POST"])
@jwt_required()
def auto_invoice_appointment(appointment_id):
    """Auto-generate invoice for an appointment based on doctor fee and test orders."""
    user = current_user()
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        raise AppError("Appointment not found", 404, "appointment_not_found")

    require_hospital_access(user, appointment.hospital_id)

    # Check if invoice already exists for this appointment
    existing = Invoice.query.filter_by(appointment_id=appointment_id, deleted_at=None).first()
    if existing:
        return jsonify({"data": {"invoice": existing.to_dict(), "already_existed": True}})

    doctor = appointment.doctor
    fee = float(doctor.consultation_fee) if doctor and doctor.consultation_fee else 0.0

    items = [
        InvoiceItem(
            item_type="consultation",
            description=f"Consultation with {doctor.professional_title} {doctor.user.full_name} ({doctor.specialty.name if doctor.specialty else 'General'})",
            quantity=1,
            unit_price=fee,
            total_price=fee,
            related_id=doctor.id
        )
    ]

    total_amount = fee
    payable = fee
    inv_number = generate_invoice_number(appointment.hospital_id)

    invoice = Invoice(
        invoice_number=inv_number,
        patient_id=appointment.patient_id,
        hospital_id=appointment.hospital_id,
        appointment_id=appointment.id,
        total_amount=total_amount,
        discount_amount=0,
        tax_amount=0,
        payable_amount=payable,
        paid_amount=0,
        due_amount=payable,
        status=InvoiceStatus.PAID.value if payable == 0 else InvoiceStatus.PENDING.value,
        notes=f"Auto-generated for Appointment #{appointment.id}",
        created_by_user_id=user.id
    )
    invoice.items = items

    db.session.add(invoice)
    db.session.commit()

    return jsonify({"data": {"invoice": invoice.to_dict(), "already_existed": False}}), 201


@bp.route("/invoices/<int:invoice_id>/payments", methods=["POST"])
@jwt_required()
def add_payment(invoice_id):
    """Record a payment towards an invoice."""
    user = current_user()
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.deleted_at is not None:
        raise AppError("Invoice not found", 404, "not_found")

    if user.role not in [Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST]:
        raise AppError("Only hospital staff can record payments", 403, "permission_denied")

    require_hospital_access(user, invoice.hospital_id)

    data = request.get_json() or {}
    amount = float(data.get("amount", 0))
    payment_method = data.get("payment_method", "cash")
    transaction_id = data.get("transaction_id", "").strip() or None
    notes = data.get("notes", "").strip() or None

    if amount <= 0:
        raise AppError("Payment amount must be greater than 0", 400, "invalid_amount")

    if amount > float(invoice.due_amount):
        raise AppError(f"Payment amount ({amount}) exceeds remaining due ({float(invoice.due_amount)})", 400, "amount_exceeds_due")

    payment_no = generate_payment_number(invoice.hospital_id)
    payment = Payment(
        payment_number=payment_no,
        invoice_id=invoice.id,
        patient_id=invoice.patient_id,
        hospital_id=invoice.hospital_id,
        amount=amount,
        payment_method=payment_method,
        transaction_id=transaction_id,
        status=PaymentStatus.COMPLETED.value,
        notes=notes,
        received_by_user_id=user.id
    )

    new_paid = float(invoice.paid_amount) + amount
    new_due = max(0.0, float(invoice.payable_amount) - new_paid)
    invoice.paid_amount = new_paid
    invoice.due_amount = new_due

    if new_due == 0:
        invoice.status = InvoiceStatus.PAID.value
        invoice.paid_at = datetime.now(timezone.utc)
    else:
        invoice.status = InvoiceStatus.PARTIAL.value

    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "data": {
            "payment": payment.to_dict(),
            "invoice": invoice.to_dict()
        }
    }), 201


@bp.route("/invoices/<int:invoice_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_invoice(invoice_id):
    """Cancel an invoice if no payments were made."""
    user = current_user()
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.deleted_at is not None:
        raise AppError("Invoice not found", 404, "not_found")

    if user.role not in [Role.SUPER_ADMIN, Role.ADMIN]:
        raise AppError("Only administrators can cancel invoices", 403, "permission_denied")

    require_hospital_access(user, invoice.hospital_id)

    if float(invoice.paid_amount) > 0:
        raise AppError("Cannot cancel an invoice with recorded payments", 400, "cannot_cancel_paid")

    invoice.status = InvoiceStatus.CANCELLED.value
    db.session.commit()

    return jsonify({"data": {"invoice": invoice.to_dict()}})


@bp.route("/stats", methods=["GET"])
@jwt_required()
def billing_stats():
    """Get billing overview stats for hospital dashboard."""
    user = current_user()
    tenant = get_current_tenant()
    hospital_id = request.args.get("hospital_id", type=int)

    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        # Default to first assigned hospital
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    query = Invoice.query.filter(Invoice.deleted_at.is_(None))
    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)

    all_invoices = query.all()

    total_billed = sum(float(inv.payable_amount) for inv in all_invoices if inv.status != InvoiceStatus.CANCELLED.value)
    total_collected = sum(float(inv.paid_amount) for inv in all_invoices)
    total_due = sum(float(inv.due_amount) for inv in all_invoices if inv.status != InvoiceStatus.CANCELLED.value)

    paid_count = sum(1 for inv in all_invoices if inv.status == InvoiceStatus.PAID.value)
    pending_count = sum(1 for inv in all_invoices if inv.status in [InvoiceStatus.PENDING.value, InvoiceStatus.PARTIAL.value])
    cancelled_count = sum(1 for inv in all_invoices if inv.status == InvoiceStatus.CANCELLED.value)

    # Payments summary
    pay_query = Payment.query
    if hospital_id:
        pay_query = pay_query.filter_by(hospital_id=hospital_id)
    payments = pay_query.all()

    method_breakdown = {}
    for p in payments:
        m = p.payment_method or "other"
        method_breakdown[m] = method_breakdown.get(m, 0.0) + float(p.amount)

    return jsonify({
        "data": {
            "total_invoices": len(all_invoices),
            "total_billed": round(total_billed, 2),
            "total_collected": round(total_collected, 2),
            "total_due": round(total_due, 2),
            "paid_count": paid_count,
            "pending_count": pending_count,
            "cancelled_count": cancelled_count,
            "payment_methods": method_breakdown
        }
    })
