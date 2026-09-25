from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import (
    Dispense,
    DispenseStatus,
    Medicine,
    MedicineCategory,
    PharmacyInventory,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Role,
    StockMovement,
    StockMovementType,
    StockStatus,
    User,
    UserStatus,
)
from app.security import current_user, require_hospital_access
from app.services.audit import log_action
from app.services.pharmacy import (
    add_stock,
    adjust_stock,
    approve_purchase_order,
    create_category,
    create_dispense,
    create_medicine,
    create_purchase_order,
    generate_dispense_number,
    generate_order_number,
    get_inventory,
    get_low_stock_alerts,
    get_medicine_catalog,
    get_pharmacy_dashboard,
    get_stock_movements,
    receive_purchase_order,
    reserve_stock,
    release_reservation,
    cancel_dispense,
    complete_dispense,
    process_return,
    update_medicine,
    write_off_expired,
)
from app.utils.responses import ok

bp = Blueprint("pharmacy", __name__, url_prefix="/api/pharmacy")


# =============================================================================
# Helpers
# =============================================================================

def require_pharmacy_access(user: User, hospital_id: int):
    """Check if user has pharmacy access for hospital."""
    require_hospital_access(user, hospital_id)
    if user.role not in {User.ROLE.SUPER_ADMIN, User.ROLE.ADMIN, User.ROLE.DOCTOR, User.ROLE.RECEPTIONIST, User.ROLE.PHARMACIST}:
        # Add PHARMACIST role check if exists, otherwise allow ADMIN/DOCTOR/RECEPTIONIST
        pass


def parse_date(date_str: str) -> date:
    """Parse date string to date object."""
    return datetime.fromisoformat(date_str).date()


# =============================================================================
# Dashboard
# =============================================================================

@bp.get("/dashboard")
@jwt_required()
def dashboard():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    data = get_pharmacy_dashboard(hospital_id)
    return ok(data)


# =============================================================================
# Medicine Catalog
# =============================================================================

@bp.get("/medicines")
@jwt_required()
def list_medicines():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", type=int)
    prescription_only = request.args.get("prescription_only", type=lambda x: x.lower() == "true")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    data = get_medicine_catalog(
        hospital_id=hospital_id,
        search=search,
        category_id=category_id,
        prescription_only=prescription_only if prescription_only is not None else None,
        page=page,
        per_page=per_page,
    )
    return ok(data)


@bp.post("/medicines")
@jwt_required()
def create_medicine_endpoint():
    user = current_user()
    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN}:
        raise AppError("Permission denied", 403, "permission_denied")

    data = request.get_json(silent=True) or {}
    required = ["generic_name"]
    for field in required:
        if not data.get(field):
            raise AppError(f"{field} is required", 400, "validation_error")

    medicine = create_medicine(data, user)
    db.session.commit()
    return ok({"id": medicine.id, "generic_name": medicine.generic_name}, "Medicine created", 201)


@bp.patch("/medicines/<int:medicine_id>")
@jwt_required()
def update_medicine_endpoint(medicine_id: int):
    user = current_user()
    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN}:
        raise AppError("Permission denied", 403, "permission_denied")

    data = request.get_json(silent=True) or {}
    medicine = update_medicine(medicine_id, data, user)
    db.session.commit()
    return ok({"id": medicine.id}, "Medicine updated")


# =============================================================================
# Medicine Categories
# =============================================================================

@bp.get("/categories")
@jwt_required()
def list_categories():
    user = current_user()
    categories = MedicineCategory.query.filter_by(is_active=True).order_by(MedicineCategory.name).all()
    return ok({"categories": [
        {"id": c.id, "name": c.name, "description": c.description}
        for c in categories
    ]})


@bp.post("/categories")
@jwt_required()
def create_category_endpoint():
    user = current_user()
    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN}:
        raise AppError("Permission denied", 403, "permission_denied")

    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        raise AppError("name is required", 400, "validation_error")

    category = create_category(data, user)
    db.session.commit()
    return ok({"id": category.id, "name": category.name}, "Category created", 201)


# =============================================================================
# Inventory
# =============================================================================

@bp.get("/inventory")
@jwt_required()
def list_inventory():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    search = request.args.get("search", "").strip()
    status = request.args.get("status")  # in_stock, low_stock, out_of_stock, expired, near_expiry
    expiry_days = request.args.get("expiry_days", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    data = get_inventory(hospital_id, search, status, expiry_days, page, per_page)
    return ok(data)


@bp.get("/inventory/alerts")
@jwt_required()
def inventory_alerts():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    threshold = request.args.get("threshold", 10, type=int)
    alerts = get_low_stock_alerts(hospital_id, threshold)
    return ok({"alerts": alerts, "count": len(alerts)})


@bp.post("/inventory/add")
@jwt_required()
def add_stock_endpoint():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    data = request.get_json(silent=True) or {}
    required = ["medicine_id", "quantity", "batch_number", "expiry_date"]
    for field in required:
        if not data.get(field):
            raise AppError(f"{field} is required", 400, "validation_error")

    inventory = add_stock(
        hospital_id=hospital_id,
        medicine_id=data["medicine_id"],
        quantity=data["quantity"],
        batch_number=data["batch_number"],
        expiry_date=parse_date(data["expiry_date"]),
        unit_price=Decimal(str(data["unit_price"])) if data.get("unit_price") else None,
        purchase_price=Decimal(str(data["purchase_price"])) if data.get("purchase_price") else None,
        location=data.get("location"),
        supplier=data.get("supplier"),
        supplier_invoice=data.get("supplier_invoice"),
        notes=data.get("notes"),
        user=user,
        movement_type=StockMovementType(data.get("movement_type", "purchase")),
        reference_type=data.get("reference_type"),
        reference_id=int(data.get("reference_id")) if data.get("reference_id") else None,
        reference_number=data.get("reference_number"),
    )
    db.session.commit()
    return ok(inventory.to_dict(), "Stock added")


@bp.post("/inventory/<int:inventory_id>/adjust")
@jwt_required()
def adjust_stock_endpoint(inventory_id: int):
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    data = request.get_json(silent=True) or {}
    new_quantity = data.get("new_quantity")
    if new_quantity is None:
        raise AppError("new_quantity required", 400, "validation_error")

    inventory = adjust_stock(inventory_id, new_quantity, user, data.get("notes", ""))
    db.session.commit()
    return ok(inventory.to_dict(), "Stock adjusted")


@bp.post("/inventory/write-off-expired")
@jwt_required()
def write_off_expired_endpoint():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    count = write_off_expired(hospital_id, user)
    db.session.commit()
    return ok({"written_off": count}, f"Written off {count} expired batches")


# =============================================================================
# Stock Movements (Audit Trail)
# =============================================================================

@bp.get("/movements")
@jwt_required()
def list_movements():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    inventory_id = request.args.get("inventory_id", type=int)
    movement_type = request.args.get("movement_type")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)

    data = get_stock_movements(
        hospital_id,
        inventory_id=inventory_id,
        movement_type=movement_type,
        start_date=parse_date(start_date) if start_date else None,
        end_date=parse_date(end_date) if end_date else None,
        page=page,
        per_page=per_page,
    )
    return ok(data)


# =============================================================================
# Purchase Orders
# =============================================================================

@bp.get("/purchase-orders")
@jwt_required()
def list_purchase_orders():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    status = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = PurchaseOrder.query.filter_by(hospital_id=hospital_id)
    if status:
        query = query.filter_by(status=status)

    query = query.order_by(PurchaseOrder.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return ok({
        "items": [po.to_dict() for po in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    })


@bp.get("/purchase-orders/<int:po_id>")
@jwt_required()
def get_purchase_order(po_id: int):
    user = current_user()
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        raise AppError("Purchase order not found", 404, "not_found")
    require_hospital_access(user, po.hospital_id)
    return ok(po.to_dict())


@bp.post("/purchase-orders")
@jwt_required()
def create_purchase_order_endpoint():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN}:
        raise AppError("Permission denied", 403, "permission_denied")

    data = request.get_json(silent=True) or {}
    required = ["supplier", "items"]
    for field in required:
        if not data.get(field):
            raise AppError(f"{field} is required", 400, "validation_error")

    if not data["items"]:
        raise AppError("At least one item required", 400, "validation_error")

    po = create_purchase_order(hospital_id, data, user)
    db.session.commit()
    return ok(po.to_dict(), "Purchase order created", 201)


@bp.post("/purchase-orders/<int:po_id>/approve")
@jwt_required()
def approve_purchase_order_endpoint(po_id: int):
    user = current_user()
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        raise AppError("Purchase order not found", 404, "not_found")
    require_hospital_access(user, po.hospital_id)

    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN}:
        raise AppError("Permission denied", 403, "permission_denied")

    po = approve_purchase_order(po_id, user)
    db.session.commit()
    return ok(po.to_dict(), "Purchase order approved")


@bp.post("/purchase-orders/<int:po_id>/receive")
@jwt_required()
def receive_purchase_order_endpoint(po_id: int):
    user = current_user()
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        raise AppError("Purchase order not found", 404, "not_found")
    require_hospital_access(user, po.hospital_id)

    data = request.get_json(silent=True) or {}
    received_items = data.get("items", [])
    if not received_items:
        raise AppError("items required", 400, "validation_error")

    po = receive_purchase_order(po_id, received_items, user)
    db.session.commit()
    return ok(po.to_dict(), "Purchase order received")


# =============================================================================
# Dispense
# =============================================================================

@bp.get("/dispenses")
@jwt_required()
def list_dispenses():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    status = request.args.get("status")
    prescription_id = request.args.get("prescription_id", type=int)
    patient_id = request.args.get("patient_id", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Dispense.query.filter_by(hospital_id=hospital_id)
    if status:
        query = query.filter_by(status=status)
    if prescription_id:
        query = query.filter_by(prescription_id=prescription_id)
    if patient_id:
        query = query.filter_by(patient_id=patient_id)

    query = query.order_by(Dispense.dispense_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return ok({
        "items": [d.to_dict() for d in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    })


@bp.get("/dispenses/<int:dispense_id>")
@jwt_required()
def get_dispense(dispense_id: int):
    user = current_user()
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise AppError("Dispense not found", 404, "not_found")
    require_hospital_access(user, dispense.hospital_id)
    return ok(dispense.to_dict())


@bp.post("/dispenses")
@jwt_required()
def create_dispense_endpoint():
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    data = request.get_json(silent=True) or {}
    required = ["items"]
    for field in required:
        if not data.get(field):
            raise AppError(f"{field} is required", 400, "validation_error")

    if not data["items"]:
        raise AppError("At least one item required", 400, "validation_error")

    # Check prescription access if provided
    if data.get("prescription_id"):
        from app.models import Prescription
        prescription = db.session.get(Prescription, data["prescription_id"])
        if not prescription:
            raise AppError("Prescription not found", 404, "not_found")
        if prescription.hospital_id != hospital_id:
            raise AppError("Prescription not from this hospital", 403, "hospital_access_denied")

    dispense = create_dispense(hospital_id, data, user)
    db.session.commit()
    return ok(dispense.to_dict(), "Dispense created", 201)


@bp.post("/dispenses/<int:dispense_id>/complete")
@jwt_required()
def complete_dispense_endpoint(dispense_id: int):
    user = current_user()
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise AppError("Dispense not found", 404, "not_found")
    require_hospital_access(user, dispense.hospital_id)

    data = request.get_json(silent=True) or {}
    payment_method = data.get("payment_method")
    paid_amount = Decimal(str(data["paid_amount"])) if data.get("paid_amount") else None

    dispense = complete_dispense(dispense_id, user, payment_method, paid_amount)
    db.session.commit()
    return ok(dispense.to_dict(), "Dispense completed")


@bp.post("/dispenses/<int:dispense_id>/cancel")
@jwt_required()
def cancel_dispense_endpoint(dispense_id: int):
    user = current_user()
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise AppError("Dispense not found", 404, "not_found")
    require_hospital_access(user, dispense.hospital_id)

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "")

    dispense = cancel_dispense(dispense_id, user, reason)
    db.session.commit()
    return ok(dispense.to_dict(), "Dispense cancelled")


@bp.post("/dispenses/<int:dispense_id>/return")
@jwt_required()
def return_dispense_endpoint(dispense_id: int):
    user = current_user()
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise AppError("Dispense not found", 404, "not_found")
    require_hospital_access(user, dispense.hospital_id)

    data = request.get_json(silent=True) or {}
    return_items = data.get("items", [])
    if not return_items:
        raise AppError("items required", 400, "validation_error")

    dispense = process_return(dispense_id, return_items, user)
    db.session.commit()
    return ok(dispense.to_dict(), "Return processed")


# =============================================================================
# Prescription-based Dispense (from finalized prescriptions)
# =============================================================================

@bp.post("/dispense-from-prescription/<int:prescription_id>")
@jwt_required()
def dispense_from_prescription(prescription_id: int):
    """Create dispense directly from a finalized prescription."""
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    if not hospital_id:
        raise AppError("hospital_id required", 400, "hospital_id_required")
    require_hospital_access(user, hospital_id)

    from app.models import Prescription, PrescriptionStatus
    prescription = db.session.get(Prescription, prescription_id)
    if not prescription:
        raise AppError("Prescription not found", 404, "not_found")
    if prescription.hospital_id != hospital_id:
        raise AppError("Prescription not from this hospital", 403, "hospital_access_denied")
    if prescription.status != PrescriptionStatus.FINALIZED:
        raise AppError("Prescription must be finalized", 400, "invalid_status")

    # Check if already dispensed
    existing = Dispense.query.filter_by(prescription_id=prescription_id, status=DispenseStatus.COMPLETED).first()
    if existing:
        raise AppError("Prescription already dispensed", 409, "already_dispensed")

    # Build dispense items from prescription
    items = []
    for pi in prescription.items:
        items.append({
            "medicine_id": pi.medicine_id,
            "quantity": 1,  # Default, frontend can modify
            "notes": pi.instructions,
        })

    dispense_data = {
        "prescription_id": prescription_id,
        "patient_id": prescription.patient_id,
        "items": items,
        "notes": f"From prescription {prescription.prescription_code}",
    }

    dispense = create_dispense(hospital_id, dispense_data, user)
    db.session.commit()
    return ok(dispense.to_dict(), "Dispense created from prescription", 201)