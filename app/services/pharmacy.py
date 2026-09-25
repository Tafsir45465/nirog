from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from flask import current_app

from app.extensions import db
from app.models import (
    Dispense,
    DispenseItem,
    DispenseStatus,
    Medicine,
    MedicineCategory,
    PharmacyInventory,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    StockMovement,
    StockMovementType,
    StockStatus,
    User,
    utcnow,
)
from app.services.audit import log_action


def generate_order_number(prefix: str = "PO") -> str:
    """Generate unique order number."""
    from uuid import uuid4
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"


def generate_dispense_number(prefix: str = "DISP") -> str:
    """Generate unique dispense number."""
    from uuid import uuid4
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"


def generate_batch_number() -> str:
    """Generate batch number."""
    from uuid import uuid4
    return f"BATCH-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"


# =============================================================================
# Medicine Catalog Services
# =============================================================================

def create_medicine(data: dict, user: User) -> Medicine:
    """Create a new medicine in the catalog."""
    category_id = data.get("category_id")
    if category_id:
        category = db.session.get(MedicineCategory, category_id)
        if not category:
            raise ValueError("Category not found")

    medicine = Medicine(
        category_id=category_id,
        generic_name=data["generic_name"].strip(),
        brand_name=data.get("brand_name", "").strip() or None,
        strength=data.get("strength"),
        dosage_form=data.get("dosage_form"),
        manufacturer=data.get("manufacturer"),
        unit=data.get("unit"),
        default_instructions=data.get("default_instructions"),
        unit_price=Decimal(str(data.get("unit_price", 0))),
        purchase_price=Decimal(str(data.get("purchase_price", 0))),
        tax_percentage=Decimal(str(data.get("tax_percentage", 0))),
        is_prescription_only=data.get("is_prescription_only", False),
        controlled_substance=data.get("controlled_substance", False),
        barcode=data.get("barcode"),
        is_active=data.get("is_active", True),
    )
    db.session.add(medicine)
    db.session.flush()

    log_action(user, "medicine.created", "Medicine", medicine.id, after=medicine.to_dict() if hasattr(medicine, 'to_dict') else None)
    return medicine


def update_medicine(medicine_id: int, data: dict, user: User) -> Medicine:
    """Update medicine catalog entry."""
    medicine = db.session.get(Medicine, medicine_id)
    if not medicine:
        raise ValueError("Medicine not found")

    before = {k: getattr(medicine, k) for k in [
        'generic_name', 'brand_name', 'strength', 'dosage_form', 'manufacturer',
        'unit', 'default_instructions', 'unit_price', 'purchase_price',
        'tax_percentage', 'is_prescription_only', 'controlled_substance',
        'barcode', 'is_active', 'category_id'
    ]}

    for field in ['generic_name', 'brand_name', 'strength', 'dosage_form', 'manufacturer',
                  'unit', 'default_instructions', 'barcode']:
        if field in data:
            setattr(medicine, field, data[field].strip() if data[field] else None)

    for field in ['unit_price', 'purchase_price', 'tax_percentage']:
        if field in data:
            setattr(medicine, field, Decimal(str(data[field])))

    for field in ['is_prescription_only', 'controlled_substance', 'is_active']:
        if field in data:
            setattr(medicine, field, bool(data[field]))

    if "category_id" in data:
        medicine.category_id = data["category_id"] if data["category_id"] else None

    db.session.flush()
    log_action(user, "medicine.updated", "Medicine", medicine.id, before=before, after={k: getattr(medicine, k) for k in before.keys()})
    return medicine


def get_medicine_catalog(hospital_id: Optional[int] = None, search: str = "", category_id: Optional[int] = None, 
                         prescription_only: Optional[bool] = None, page: int = 1, per_page: int = 50):
    """Get paginated medicine catalog with optional filters."""
    query = Medicine.query.filter_by(is_active=True)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Medicine.generic_name.ilike(pattern)) |
            (Medicine.brand_name.ilike(pattern)) |
            (Medicine.barcode.ilike(pattern))
        )

    if category_id:
        query = query.filter_by(category_id=category_id)

    if prescription_only is not None:
        query = query.filter_by(is_prescription_only=prescription_only)

    # If hospital_id provided, join with inventory to show stock status
    if hospital_id:
        query = query.outerjoin(PharmacyInventory, (PharmacyInventory.medicine_id == Medicine.id) & (PharmacyInventory.hospital_id == hospital_id))

    query = query.order_by(Medicine.generic_name)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    items = []
    for med in pagination.items:
        item = {
            "id": med.id,
            "category_id": med.category_id,
            "category_name": med.category.name if med.category else None,
            "generic_name": med.generic_name,
            "brand_name": med.brand_name,
            "strength": med.strength,
            "dosage_form": med.dosage_form,
            "manufacturer": med.manufacturer,
            "unit": med.unit,
            "default_instructions": med.default_instructions,
            "unit_price": float(med.unit_price),
            "purchase_price": float(med.purchase_price),
            "tax_percentage": float(med.tax_percentage),
            "is_prescription_only": med.is_prescription_only,
            "controlled_substance": med.controlled_substance,
            "barcode": med.barcode,
            "is_active": med.is_active,
        }
        # Add stock info if hospital context
        if hospital_id:
            inv = PharmacyInventory.query.filter_by(hospital_id=hospital_id, medicine_id=med.id).first()
            if inv:
                item["stock_quantity"] = inv.available_quantity
                item["stock_status"] = inv.stock_status.value
                item["batch_number"] = inv.batch_number
                item["expiry_date"] = inv.expiry_date.isoformat() if inv.expiry_date else None
            else:
                item["stock_quantity"] = 0
                item["stock_status"] = StockStatus.OUT_OF_STOCK.value
        items.append(item)

    return {
        "items": items,
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    }


def create_category(data: dict, user: User) -> MedicineCategory:
    """Create medicine category."""
    category = MedicineCategory(
        name=data["name"].strip(),
        description=data.get("description"),
        is_active=data.get("is_active", True),
    )
    db.session.add(category)
    db.session.flush()
    log_action(user, "medicine_category.created", "MedicineCategory", category.id)
    return category


# =============================================================================
# Inventory Services
# =============================================================================

def get_inventory(hospital_id: int, search: str = "", status: Optional[str] = None,
                  expiry_days: Optional[int] = None, page: int = 1, per_page: int = 50):
    """Get pharmacy inventory with filters."""
    query = PharmacyInventory.query.filter_by(hospital_id=hospital_id).join(Medicine)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Medicine.generic_name.ilike(pattern)) |
            (Medicine.brand_name.ilike(pattern)) |
            (PharmacyInventory.batch_number.ilike(pattern)) |
            (PharmacyInventory.barcode.ilike(pattern))
        )

    if status:
        # Filter by computed stock status
        query = query.filter(PharmacyInventory.quantity > 0 if status != StockStatus.OUT_OF_STOCK.value else PharmacyInventory.quantity <= 0)

    if expiry_days is not None:
        cutoff = date.today()
        from datetime import timedelta
        cutoff = cutoff + timedelta(days=expiry_days)
        query = query.filter(PharmacyInventory.expiry_date <= cutoff)

    query = query.order_by(PharmacyInventory.expiry_date.asc(), Medicine.generic_name)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        "items": [inv.to_dict() for inv in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    }


def get_low_stock_alerts(hospital_id: int, threshold: int = 10):
    """Get items below threshold or near expiry."""
    items = PharmacyInventory.query.filter_by(hospital_id=hospital_id).join(Medicine).all()
    alerts = []
    for inv in items:
        if inv.stock_status in (StockStatus.LOW_STOCK, StockStatus.OUT_OF_STOCK, StockStatus.NEAR_EXPIRY, StockStatus.EXPIRED):
            alerts.append(inv.to_dict())
    return alerts


def add_stock(hospital_id: int, medicine_id: int, quantity: int, batch_number: str, expiry_date: date,
              unit_price: Optional[Decimal] = None, purchase_price: Optional[Decimal] = None,
              location: str = None, supplier: str = None, supplier_invoice: str = None,
              notes: str = None, user: User = None, movement_type: StockMovementType = StockMovementType.PURCHASE,
              reference_type: str = None, reference_id: int = None, reference_number: str = None) -> PharmacyInventory:
    """Add stock to inventory (creates new batch or updates existing)."""
    # Find existing batch
    inventory = PharmacyInventory.query.filter_by(
        hospital_id=hospital_id,
        medicine_id=medicine_id,
        batch_number=batch_number
    ).first()

    medicine = db.session.get(Medicine, medicine_id)
    if not medicine:
        raise ValueError("Medicine not found")

    previous_quantity = 0
    if inventory:
        previous_quantity = inventory.quantity
        inventory.quantity += quantity
        if unit_price is not None:
            inventory.unit_price_override = unit_price
        if purchase_price is not None:
            inventory.purchase_price_override = purchase_price
        if location:
            inventory.location = location
        if supplier:
            inventory.supplier = supplier
        if supplier_invoice:
            inventory.supplier_invoice = supplier_invoice
        if notes:
            inventory.notes = notes
    else:
        inventory = PharmacyInventory(
            hospital_id=hospital_id,
            medicine_id=medicine_id,
            batch_number=batch_number,
            expiry_date=expiry_date,
            quantity=quantity,
            unit_price_override=unit_price,
            purchase_price_override=purchase_price,
            location=location,
            supplier=supplier,
            supplier_invoice=supplier_invoice,
            received_date=date.today(),
            notes=notes,
        )
        db.session.add(inventory)

    db.session.flush()

    # Create stock movement record
    movement = StockMovement(
        hospital_id=hospital_id,
        inventory_id=inventory.id,
        movement_type=movement_type,
        quantity=quantity,
        previous_quantity=previous_quantity,
        new_quantity=inventory.quantity,
        unit_cost=purchase_price or medicine.purchase_price,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=notes,
        created_by_user_id=user.id if user else None,
    )
    db.session.add(movement)

    log_action(user, f"stock.{movement_type.value}", "PharmacyInventory", inventory.id,
               after={"quantity": inventory.quantity, "batch": batch_number})

    return inventory


def reserve_stock(inventory_id: int, quantity: int, user: User, reference_type: str, reference_id: int, reference_number: str) -> bool:
    """Reserve stock for pending dispense/order."""
    inventory = db.session.get(PharmacyInventory, inventory_id)
    if not inventory:
        raise ValueError("Inventory not found")

    if inventory.available_quantity < quantity:
        raise ValueError(f"Insufficient stock. Available: {inventory.available_quantity}")

    previous_reserved = inventory.reserved_quantity
    inventory.reserved_quantity += quantity
    db.session.flush()

    movement = StockMovement(
        hospital_id=inventory.hospital_id,
        inventory_id=inventory.id,
        movement_type=StockMovementType.RESERVED,
        quantity=quantity,
        previous_quantity=previous_reserved,
        new_quantity=inventory.reserved_quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=f"Reserved {quantity} units",
        created_by_user_id=user.id if user else None,
    )
    db.session.add(movement)
    return True


def release_reservation(inventory_id: int, quantity: int, user: User, reference_type: str, reference_id: int, reference_number: str) -> bool:
    """Release reserved stock."""
    inventory = db.session.get(PharmacyInventory, inventory_id)
    if not inventory:
        raise ValueError("Inventory not found")

    if inventory.reserved_quantity < quantity:
        raise ValueError("Cannot release more than reserved")

    previous_reserved = inventory.reserved_quantity
    inventory.reserved_quantity -= quantity
    db.session.flush()

    movement = StockMovement(
        hospital_id=inventory.hospital_id,
        inventory_id=inventory.id,
        movement_type=StockMovementType.RELEASED,
        quantity=-quantity,
        previous_quantity=previous_reserved,
        new_quantity=inventory.reserved_quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=f"Released {quantity} units",
        created_by_user_id=user.id if user else None,
    )
    db.session.add(movement)
    return True


def adjust_stock(inventory_id: int, new_quantity: int, user: User, notes: str = "") -> PharmacyInventory:
    """Manual stock adjustment (cycle count, damage, etc.)."""
    inventory = db.session.get(PharmacyInventory, inventory_id)
    if not inventory:
        raise ValueError("Inventory not found")

    if new_quantity < inventory.reserved_quantity:
        raise ValueError("Cannot adjust below reserved quantity")

    previous = inventory.quantity
    inventory.quantity = new_quantity
    db.session.flush()

    movement = StockMovement(
        hospital_id=inventory.hospital_id,
        inventory_id=inventory.id,
        movement_type=StockMovementType.ADJUSTMENT,
        quantity=new_quantity - previous,
        previous_quantity=previous,
        new_quantity=new_quantity,
        unit_cost=inventory.get_effective_price("purchase"),
        reference_type="adjustment",
        notes=notes or f"Adjusted from {previous} to {new_quantity}",
        created_by_user_id=user.id if user else None,
    )
    db.session.add(movement)

    log_action(user, "stock.adjusted", "PharmacyInventory", inventory.id,
               before={"quantity": previous}, after={"quantity": new_quantity})
    return inventory


def write_off_expired(hospital_id: int, user: User) -> int:
    """Write off expired stock."""
    from datetime import date
    expired = PharmacyInventory.query.filter(
        PharmacyInventory.hospital_id == hospital_id,
        PharmacyInventory.expiry_date < date.today(),
        PharmacyInventory.quantity > 0
    ).all()

    count = 0
    for inv in expired:
        previous = inv.quantity
        inv.quantity = 0
        movement = StockMovement(
            hospital_id=hospital_id,
            inventory_id=inv.id,
            movement_type=StockMovementType.EXPIRED,
            quantity=-previous,
            previous_quantity=previous,
            new_quantity=0,
            unit_cost=inv.get_effective_price("purchase"),
            reference_type="expired_writeoff",
            notes=f"Auto write-off: expired on {inv.expiry_date}",
            created_by_user_id=user.id if user else None,
        )
        db.session.add(movement)
        count += 1

    return count


# =============================================================================
# Purchase Order Services
# =============================================================================

def create_purchase_order(hospital_id: int, data: dict, user: User) -> PurchaseOrder:
    """Create a new purchase order."""
    po = PurchaseOrder(
        hospital_id=hospital_id,
        supplier=data["supplier"],
        supplier_contact=data.get("supplier_contact"),
        order_number=generate_order_number(),
        status=PurchaseOrderStatus.DRAFT,
        order_date=utcnow(),
        expected_delivery_date=datetime.fromisoformat(data["expected_delivery_date"]).date() if data.get("expected_delivery_date") else None,
        notes=data.get("notes"),
        created_by_user_id=user.id,
    )
    db.session.add(po)
    db.session.flush()

    # Add items
    total = Decimal("0")
    tax_total = Decimal("0")
    discount_total = Decimal("0")

    for item_data in data.get("items", []):
        medicine = db.session.get(Medicine, item_data["medicine_id"])
        if not medicine:
            raise ValueError(f"Medicine {item_data['medicine_id']} not found")

        qty = item_data["quantity_ordered"]
        unit_price = Decimal(str(item_data["unit_price"]))
        tax_pct = Decimal(str(item_data.get("tax_percentage", 0)))
        discount_pct = Decimal(str(item_data.get("discount_percentage", 0)))

        item = PurchaseOrderItem(
            purchase_order_id=po.id,
            medicine_id=medicine.id,
            quantity_ordered=qty,
            unit_price=unit_price,
            tax_percentage=tax_pct,
            discount_percentage=discount_pct,
            batch_number=item_data.get("batch_number") or generate_batch_number(),
            expiry_date=datetime.fromisoformat(item_data["expiry_date"]).date() if item_data.get("expiry_date") else None,
            notes=item_data.get("notes"),
        )
        db.session.add(item)

        line_price = unit_price * qty
        tax_total += line_price * (tax_pct / 100)
        discount_total += line_price * (discount_pct / 100)
        total += line_price

    po.total_amount = total
    po.tax_amount = tax_total
    po.discount_amount = discount_total
    po.payable_amount = total + tax_total - discount_total

    log_action(user, "purchase_order.created", "PurchaseOrder", po.id)
    return po


def approve_purchase_order(po_id: int, user: User) -> PurchaseOrder:
    """Approve a purchase order."""
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        raise ValueError("Purchase order not found")

    if po.status != PurchaseOrderStatus.DRAFT:
        raise ValueError("Only draft orders can be approved")

    po.status = PurchaseOrderStatus.APPROVED
    po.approved_by_user_id = user.id
    po.approved_at = utcnow()
    db.session.flush()

    log_action(user, "purchase_order.approved", "PurchaseOrder", po.id)
    return po


def receive_purchase_order(po_id: int, received_items: list, user: User) -> PurchaseOrder:
    """Receive items against a purchase order."""
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        raise ValueError("Purchase order not found")

    if po.status not in (PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIAL_RECEIVED):
        raise ValueError("Cannot receive for this order status")

    all_received = True
    for received in received_items:
        item = db.session.get(PurchaseOrderItem, received["item_id"])
        if not item or item.purchase_order_id != po_id:
            raise ValueError("Invalid item")

        qty_received = received["quantity_received"]
        if qty_received > item.quantity_pending:
            raise ValueError(f"Cannot receive more than pending for {item.medicine.generic_name}")

        item.quantity_received += qty_received

        # Add to inventory
        add_stock(
            hospital_id=po.hospital_id,
            medicine_id=item.medicine_id,
            quantity=qty_received,
            batch_number=received.get("batch_number") or item.batch_number or generate_batch_number(),
            expiry_date=datetime.fromisoformat(received["expiry_date"]).date() if received.get("expiry_date") else (item.expiry_date or date.today()),
            unit_price=None,  # Use medicine default selling price
            purchase_price=item.unit_price,
            location=received.get("location"),
            supplier=po.supplier,
            supplier_invoice=received.get("supplier_invoice"),
            notes=received.get("notes"),
            user=user,
            movement_type=StockMovementType.PURCHASE,
            reference_type="purchase_order",
            reference_id=po.id,
            reference_number=po.order_number,
        )

        if item.quantity_pending > 0:
            all_received = False

    po.status = PurchaseOrderStatus.RECEIVED if all_received else PurchaseOrderStatus.PARTIAL_RECEIVED
    if all_received:
        po.received_date = utcnow()

    db.session.flush()
    log_action(user, "purchase_order.received", "PurchaseOrder", po.id)
    return po


# =============================================================================
# Dispense Services
# =============================================================================

def create_dispense(hospital_id: int, data: dict, user: User) -> Dispense:
    """Create a new dispense (from prescription or walk-in)."""
    prescription_id = data.get("prescription_id")
    patient_id = data.get("patient_id")

    if not prescription_id and not patient_id:
        raise ValueError("Either prescription_id or patient_id required")

    if prescription_id:
        from app.models import Prescription
        prescription = db.session.get(Prescription, prescription_id)
        if not prescription:
            raise ValueError("Prescription not found")
        if prescription.hospital_id != hospital_id:
            raise ValueError("Prescription not from this hospital")
        if prescription.status != "finalized":
            raise ValueError("Prescription must be finalized")
        patient_id = prescription.patient_id

    dispense = Dispense(
        hospital_id=hospital_id,
        prescription_id=prescription_id,
        patient_id=patient_id,
        dispense_number=generate_dispense_number(),
        status=DispenseStatus.PENDING,
        dispense_date=utcnow(),
        notes=data.get("notes"),
        dispensed_by_user_id=user.id,
    )
    db.session.add(dispense)
    db.session.flush()

    # Add items and reserve stock
    total = Decimal("0")
    tax_total = Decimal("0")
    discount_total = Decimal("0")

    for item_data in data.get("items", []):
        medicine_id = item_data["medicine_id"]
        quantity = item_data["quantity"]

        # Find best batch (FEFO - First Expired First Out)
        inventory = PharmacyInventory.query.filter(
            PharmacyInventory.hospital_id == hospital_id,
            PharmacyInventory.medicine_id == medicine_id,
            PharmacyInventory.quantity > PharmacyInventory.reserved_quantity,
            PharmacyInventory.expiry_date >= date.today()
        ).order_by(PharmacyInventory.expiry_date.asc()).first()

        if not inventory:
            raise ValueError(f"No stock available for medicine {medicine_id}")

        if inventory.available_quantity < quantity:
            raise ValueError(f"Insufficient stock for {inventory.medicine.generic_name}. Available: {inventory.available_quantity}")

        # Reserve stock
        reserve_stock(inventory.id, quantity, user, "dispense", dispense.id, dispense.dispense_number)

        medicine = db.session.get(Medicine, medicine_id)
        unit_price = Decimal(str(item_data.get("unit_price", inventory.get_effective_price("sell"))))
        tax_pct = Decimal(str(item_data.get("tax_percentage", medicine.tax_percentage if medicine else 0)))
        discount_pct = Decimal(str(item_data.get("discount_percentage", 0)))

        item = DispenseItem(
            dispense_id=dispense.id,
            inventory_id=inventory.id,
            medicine_id=medicine_id,
            quantity=quantity,
            unit_price=unit_price,
            tax_percentage=tax_pct,
            discount_percentage=discount_pct,
            batch_number=inventory.batch_number,
            expiry_date=inventory.expiry_date,
            notes=item_data.get("notes"),
        )
        db.session.add(item)

        line_price = unit_price * quantity
        tax_total += line_price * (tax_pct / 100)
        discount_total += line_price * (discount_pct / 100)
        total += line_price

    dispense.total_amount = total
    dispense.tax_amount = tax_total
    dispense.discount_amount = discount_total
    dispense.payable_amount = total + tax_total - discount_total

    db.session.flush()
    log_action(user, "dispense.created", "Dispense", dispense.id)
    return dispense


def complete_dispense(dispense_id: int, user: User, payment_method: str = None, paid_amount: Decimal = None) -> Dispense:
    """Complete a dispense (actually reduce stock)."""
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise ValueError("Dispense not found")

    if dispense.status not in (DispenseStatus.PENDING, DispenseStatus.PARTIAL):
        raise ValueError("Dispense already completed or cancelled")

    # Release reservations and actually reduce stock
    for item in dispense.items:
        inventory = db.session.get(PharmacyInventory, item.inventory_id)
        if not inventory:
            continue

        # Release reservation
        release_reservation(
            inventory.id, item.quantity, user,
            "dispense", dispense.id, dispense.dispense_number
        )

        # Reduce actual stock
        previous = inventory.quantity
        inventory.quantity -= item.quantity

        movement = StockMovement(
            hospital_id=inventory.hospital_id,
            inventory_id=inventory.id,
            movement_type=StockMovementType.SALE,
            quantity=-item.quantity,
            previous_quantity=previous,
            new_quantity=inventory.quantity,
            unit_cost=inventory.get_effective_price("purchase"),
            reference_type="dispense",
            reference_id=dispense.id,
            reference_number=dispense.dispense_number,
            notes=f"Dispensed {item.quantity} units",
            created_by_user_id=user.id,
        )
        db.session.add(movement)

    dispense.status = DispenseStatus.COMPLETED
    dispense.payment_method = payment_method
    dispense.paid_amount = paid_amount or dispense.payable_amount
    dispense.verified_by_user_id = user.id

    db.session.flush()
    log_action(user, "dispense.completed", "Dispense", dispense.id)
    return dispense


def cancel_dispense(dispense_id: int, user: User, reason: str = "") -> Dispense:
    """Cancel a pending dispense and release reservations."""
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise ValueError("Dispense not found")

    if dispense.status == DispenseStatus.COMPLETED:
        raise ValueError("Cannot cancel completed dispense")

    # Release all reservations
    for item in dispense.items:
        release_reservation(
            item.inventory_id, item.quantity, user,
            "dispense", dispense.id, dispense.dispense_number
        )

    dispense.status = DispenseStatus.CANCELLED
    dispense.notes = (dispense.notes or "") + f"\nCancelled: {reason}"
    db.session.flush()

    log_action(user, "dispense.cancelled", "Dispense", dispense.id)
    return dispense


def process_return(dispense_id: int, return_items: list, user: User) -> Dispense:
    """Process medicine return from patient."""
    dispense = db.session.get(Dispense, dispense_id)
    if not dispense:
        raise ValueError("Dispense not found")

    if dispense.status != DispenseStatus.COMPLETED:
        raise ValueError("Can only return from completed dispense")

    for ret in return_items:
        item = db.session.get(DispenseItem, ret["dispense_item_id"])
        if not item or item.dispense_id != dispense_id:
            raise ValueError("Invalid dispense item")

        qty = ret["quantity"]
        if qty > item.quantity:
            raise ValueError("Cannot return more than dispensed")

        # Add back to inventory (same batch if possible)
        inventory = db.session.get(PharmacyInventory, item.inventory_id)
        if inventory and inventory.batch_number == item.batch_number:
            add_stock(
                hospital_id=dispense.hospital_id,
                medicine_id=item.medicine_id,
                quantity=qty,
                batch_number=item.batch_number,
                expiry_date=item.expiry_date or date.today(),
                purchase_price=inventory.get_effective_price("purchase"),
                user=user,
                movement_type=StockMovementType.RETURN,
                reference_type="dispense_return",
                reference_id=dispense.id,
                reference_number=dispense.dispense_number,
                notes=f"Return: {ret.get('reason', '')}"
            )
        else:
            # Create new inventory entry for return
            add_stock(
                hospital_id=dispense.hospital_id,
                medicine_id=item.medicine_id,
                quantity=qty,
                batch_number=generate_batch_number(),
                expiry_date=item.expiry_date or date.today(),
                user=user,
                movement_type=StockMovementType.RETURN,
                reference_type="dispense_return",
                reference_id=dispense.id,
                reference_number=dispense.dispense_number,
                notes=f"Return (different batch): {ret.get('reason', '')}"
            )

    dispense.status = DispenseStatus.RETURNED
    db.session.flush()

    log_action(user, "dispense.returned", "Dispense", dispense.id)
    return dispense


# =============================================================================
# Stock Movement / Audit
# =============================================================================

def get_stock_movements(hospital_id: int, inventory_id: int = None, movement_type: str = None,
                        start_date: date = None, end_date: date = None, page: int = 1, per_page: int = 100):
    """Get stock movement history."""
    query = StockMovement.query.filter_by(hospital_id=hospital_id)

    if inventory_id:
        query = query.filter_by(inventory_id=inventory_id)

    if movement_type:
        query = query.filter_by(movement_type=movement_type)

    if start_date:
        query = query.filter(StockMovement.created_at >= start_date)

    if end_date:
        query = query.filter(StockMovement.created_at <= end_date)

    query = query.order_by(StockMovement.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        "items": [m.to_dict() for m in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    }


# =============================================================================
# Dashboard / Analytics
# =============================================================================

def get_pharmacy_dashboard(hospital_id: int) -> dict:
    """Get pharmacy dashboard summary."""
    from sqlalchemy import func

    # Total medicines in catalog
    total_medicines = Medicine.query.filter_by(is_active=True).count()

    # Inventory stats
    inv_query = PharmacyInventory.query.filter_by(hospital_id=hospital_id)
    total_batches = inv_query.count()
    total_stock_value = inv_query.with_entities(
        func.sum(PharmacyInventory.quantity * PharmacyInventory.unit_price_override)
    ).scalar() or 0

    # Low stock count
    low_stock = 0
    expired = 0
    near_expiry = 0
    out_of_stock = 0

    for inv in inv_query.all():
        status = inv.stock_status
        if status == StockStatus.LOW_STOCK:
            low_stock += 1
        elif status == StockStatus.EXPIRED:
            expired += 1
        elif status == StockStatus.NEAR_EXPIRY:
            near_expiry += 1
        elif status == StockStatus.OUT_OF_STOCK:
            out_of_stock += 1

    # Pending POs
    pending_pos = PurchaseOrder.query.filter(
        PurchaseOrder.hospital_id == hospital_id,
        PurchaseOrder.status.in_([PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIAL_RECEIVED])
    ).count()

    # Today's dispenses
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(date.today(), datetime.max.time()).replace(tzinfo=timezone.utc)
    today_dispenses = Dispense.query.filter(
        Dispense.hospital_id == hospital_id,
        Dispense.dispense_date >= today_start,
        Dispense.dispense_date <= today_end,
        Dispense.status == DispenseStatus.COMPLETED
    ).count()

    today_revenue = db.session.query(func.sum(Dispense.payable_amount)).filter(
        Dispense.hospital_id == hospital_id,
        Dispense.dispense_date >= today_start,
        Dispense.dispense_date <= today_end,
        Dispense.status == DispenseStatus.COMPLETED
    ).scalar() or 0

    return {
        "total_medicines": total_medicines,
        "total_batches": total_batches,
        "total_stock_value": float(total_stock_value),
        "low_stock_count": low_stock,
        "expired_count": expired,
        "near_expiry_count": near_expiry,
        "out_of_stock_count": out_of_stock,
        "pending_purchase_orders": pending_pos,
        "today_dispenses": today_dispenses,
        "today_revenue": float(today_revenue),
    }