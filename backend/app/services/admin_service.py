import json
import logging
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.counter import Counter
from app.models.queue import QueueTicket
from app.schemas.admin import (
    AdminOrderVerificationDetail,
    AdminItemVerificationState,
    AdminScanItemResponse,
    AdminAnalyticsResponse,
    AdminTransactionSummary
)
from app.schemas.ws import WebSocketMessage
from app.services.websocket_manager import ws_manager

logger = logging.getLogger("fastshop.admin_service")


class AdminService:
    """Enterprise-grade service for POS Cashier Verification & Admin Operations."""

    async def _build_order_detail(
        self, 
        db: AsyncSession, 
        order: Order, 
        icons_map: Optional[Dict[str, str]] = None
    ) -> AdminOrderVerificationDetail:
        """Hydrates order detail with catalog icons and verification states."""
        # Pre-fetch product icons if not provided via batching
        if icons_map is None:
            barcodes = [item.product_barcode for item in order.items]
            icons_map = {}
            if barcodes:
                prod_stmt = select(Product.barcode, Product.icon).where(Product.barcode.in_(barcodes))
                res = await db.execute(prod_stmt)
                for b, icon in res.all():
                    icons_map[b] = icon or "📦"

        items_state: List[AdminItemVerificationState] = []
        total_expected = 0
        total_verified = 0

        for item in order.items:
            expected = item.quantity
            verified = item.verified_quantity or 0
            is_matched = verified >= expected
            total_expected += expected
            total_verified += min(verified, expected)

            items_state.append(
                AdminItemVerificationState(
                    product_barcode=item.product_barcode,
                    product_name=item.product_name,
                    expected_quantity=expected,
                    verified_quantity=verified,
                    is_matched=is_matched,
                    unit_price=item.unit_price,
                    total_price=item.total_price,
                    icon=icons_map.get(item.product_barcode, "📦")
                )
            )

        items_remaining = max(0, total_expected - total_verified)
        is_all_matched = (total_expected > 0) and (items_remaining == 0)

        return AdminOrderVerificationDetail(
            order_number=order.order_number,
            customer_identifier=order.customer_identifier,
            total_amount=order.total_amount,
            subtotal=order.subtotal,
            tax_amount=order.tax_amount,
            discount_amount=order.discount_amount,
            payment_status=order.payment_status,
            payment_method=order.payment_method,
            assigned_counter_number=order.assigned_counter_number,
            is_verified_by_cashier=order.is_verified_by_cashier,
            verification_status=order.verification_status or "PENDING",
            verification_duration_seconds=order.verification_duration_seconds,
            items_expected_count=total_expected,
            items_verified_count=total_verified,
            items_remaining_count=items_remaining,
            is_all_matched=is_all_matched,
            items=items_state,
            created_at=order.created_at
        )

    async def build_order_details_batch(
        self,
        db: AsyncSession,
        orders: List[Order]
    ) -> List[AdminOrderVerificationDetail]:
        """Batch hydrates multiple orders with catalog icons in a single database query (eliminates N+1)."""
        if not orders:
            return []
        all_barcodes = {item.product_barcode for o in orders for item in o.items}
        icons_map: Dict[str, str] = {}
        if all_barcodes:
            prod_stmt = select(Product.barcode, Product.icon).where(Product.barcode.in_(list(all_barcodes)))
            res = await db.execute(prod_stmt)
            for b, icon in res.all():
                icons_map[b] = icon or "📦"
        return [await self._build_order_detail(db, o, icons_map=icons_map) for o in orders]

    async def lookup_order(
        self,
        db: AsyncSession,
        token_or_number: str,
        counter_number: Optional[str] = None
    ) -> Optional[AdminOrderVerificationDetail]:
        """Looks up an order by raw order_number or QR token JSON payload."""
        order_num = token_or_number.strip()
        # Attempt to parse json qr token
        if "{" in token_or_number and "}" in token_or_number:
            try:
                parsed = json.loads(token_or_number)
                order_num = parsed.get("order_number") or parsed.get("orderId") or order_num
            except Exception:
                pass

        # Normalize prefix if needed
        stmt = select(Order).where(
            or_(
                Order.order_number == order_num,
                Order.order_number == f"FS-{order_num}",
                Order.order_number.ilike(f"%{order_num}%")
            )
        )
        res = await db.execute(stmt)
        order = res.scalars().first()

        if not order:
            return None

        # Counter Isolation Check: Ensure order belongs to this counter if counter_number is provided
        if counter_number:
            if not order.assigned_counter_number or order.assigned_counter_number in ("", "UNASSIGNED"):
                raise ValueError(
                    f"Order #{order.order_number} has not been assigned to a counter."
                )
            if order.assigned_counter_number != counter_number:
                raise ValueError(
                    f"Order #{order.order_number} is assigned to Counter {order.assigned_counter_number}, not Counter {counter_number}. Please direct customer to Counter {order.assigned_counter_number}."
                )

        # If order was PENDING, transition to IN_PROGRESS upon cashier scan
        if order.verification_status == "PENDING" and not order.is_verified_by_cashier:
            order.verification_status = "IN_PROGRESS"
            await db.commit()
            await db.refresh(order)

        return await self._build_order_detail(db, order)

    async def scan_physical_item(
        self,
        db: AsyncSession,
        order_number: str,
        scanned_barcode: str,
        counter_number: str = "03"
    ) -> Tuple[str, str, Optional[str], Optional[int], Optional[int], bool, AdminOrderVerificationDetail]:
        """
        Processes physical cashier barcode scan for an active customer's basket.
        Matches against line items, increments verified count, and alerts on discrepancies.
        """
        clean_barcode = scanned_barcode.strip()
        stmt = select(Order).where(Order.order_number == order_number)
        res = await db.execute(stmt)
        order = res.scalars().first()

        if not order:
            raise ValueError(f"Order #{order_number} not found.")

        # Counter Isolation Check
        if counter_number:
            if not order.assigned_counter_number or order.assigned_counter_number in ("", "UNASSIGNED"):
                raise ValueError(f"Order #{order.order_number} has not been assigned to a counter.")
            if order.assigned_counter_number != counter_number:
                raise ValueError(
                    f"Order #{order.order_number} is assigned to Counter {order.assigned_counter_number}, not Counter {counter_number}."
                )


        # Find line item matching barcode
        target_item: Optional[OrderItem] = None
        for itm in order.items:
            if itm.product_barcode == clean_barcode:
                target_item = itm
                break

        # Discrepancy Case 1: Item NOT in paid cart
        if not target_item:
            # Look up product name in catalog for clear cashier feedback
            p_stmt = select(Product).where(Product.barcode == clean_barcode)
            p_res = await db.execute(p_stmt)
            catalog_item = p_res.scalars().first()
            name = catalog_item.name if catalog_item else f"Barcode: {clean_barcode}"
            
            detail = await self._build_order_detail(db, order)
            return (
                "UNEXPECTED_ITEM",
                f"ITEM NOT IN PAID CART: {name} was not paid for in this ShopFast transaction.",
                name,
                0,
                1,
                detail.is_all_matched,
                detail
            )

        # Discrepancy Case 2: Already fully verified all expected units
        if target_item.verified_quantity >= target_item.quantity:
            detail = await self._build_order_detail(db, order)
            return (
                "OVER_SCANNED",
                f"Already fully matched all {target_item.quantity} units of {target_item.product_name}.",
                target_item.product_name,
                target_item.quantity,
                target_item.verified_quantity,
                detail.is_all_matched,
                detail
            )

        # Successful item match
        target_item.verified_quantity += 1
        await db.flush()

        detail = await self._build_order_detail(db, order)

        if detail.is_all_matched:
            order.verification_status = "CLEARED"
            order.is_verified_by_cashier = True
            order.verified_at = datetime.now(timezone.utc)
            status_code = "ALL_CLEARED"
            msg = f"✓ All {detail.items_expected_count} items matched! Customer cleared for exit."
        else:
            order.verification_status = "IN_PROGRESS"
            status_code = "MATCHED"
            msg = f"✓ Item matched: {target_item.product_name} ({target_item.verified_quantity}/{target_item.quantity})"

        await db.commit()
        await db.refresh(order)

        # Refresh detail after commit
        updated_detail = await self._build_order_detail(db, order)

        # Broadcast scan event on WebSocket
        await ws_manager.broadcast_to_channel(
            f"counter:{counter_number}",
            WebSocketMessage(
                event="VERIFICATION_PROGRESS",
                counter_number=counter_number,
                data={
                    "order_number": order.order_number,
                    "status": status_code,
                    "matched_barcode": clean_barcode,
                    "product_name": target_item.product_name,
                    "items_verified": updated_detail.items_verified_count,
                    "items_expected": updated_detail.items_expected_count,
                    "is_all_matched": updated_detail.is_all_matched
                }
            )
        )

        if updated_detail.is_all_matched:
            # Broadcast clearance globally to customer screen
            cleared_event = WebSocketMessage(
                event="ORDER_CLEARED_RELEASED",
                counter_number=counter_number,
                data={
                    "order_number": order.order_number,
                    "counter_number": counter_number,
                    "duration_seconds": order.verification_duration_seconds or 15,
                    "verified": True,
                    "verification_status": "CLEARED"
                }
            )
            await ws_manager.broadcast_to_channel(f"counter:{counter_number}", cleared_event)
            await ws_manager.broadcast_global(cleared_event)

        return (
            status_code,
            msg,
            target_item.product_name,
            target_item.quantity,
            target_item.verified_quantity,
            updated_detail.is_all_matched,
            updated_detail
        )

    async def complete_verification(
        self,
        db: AsyncSession,
        order_number: str,
        counter_number: str = "03",
        duration_seconds: Optional[int] = None
    ) -> AdminOrderVerificationDetail:
        """Finalizes order verification, sets cashier clearance and records duration."""
        stmt = select(Order).where(Order.order_number == order_number)
        res = await db.execute(stmt)
        order = res.scalars().first()

        if not order:
            raise ValueError(f"Order #{order_number} not found.")

        # Counter Isolation Check
        if counter_number:
            if not order.assigned_counter_number or order.assigned_counter_number in ("", "UNASSIGNED"):
                raise ValueError(f"Order #{order.order_number} has not been assigned to a counter.")
            if order.assigned_counter_number != counter_number:
                raise ValueError(
                    f"Order #{order.order_number} is assigned to Counter {order.assigned_counter_number}, not Counter {counter_number}."
                )

        order.is_verified_by_cashier = True
        order.verification_status = "CLEARED"
        order.verification_duration_seconds = duration_seconds if duration_seconds is not None else 17
        order.verified_at = datetime.now(timezone.utc)

        # Ensure all items marked verified
        for item in order.items:
            item.verified_quantity = item.quantity

        await db.commit()
        await db.refresh(order)

        # Broadcast completion to counter channel and global store channel
        msg = WebSocketMessage(
            event="ORDER_CLEARED_RELEASED",
            counter_number=counter_number,
            data={
                "order_number": order.order_number,
                "counter_number": counter_number,
                "duration_seconds": order.verification_duration_seconds,
                "verified": True,
                "verification_status": "CLEARED"
            }
        )
        await ws_manager.broadcast_to_channel(f"counter:{counter_number}", msg)
        await ws_manager.broadcast_global(msg)

        return await self._build_order_detail(db, order)

    async def reset_verification(
        self,
        db: AsyncSession,
        order_number: str,
        counter_number: str = "03"
    ) -> AdminOrderVerificationDetail:
        """Resets verified counts for an order to re-run verification or testing."""
        stmt = select(Order).where(Order.order_number == order_number)
        res = await db.execute(stmt)
        order = res.scalars().first()

        if not order:
            raise ValueError(f"Order #{order_number} not found.")

        # Counter Isolation Check
        if counter_number:
            if not order.assigned_counter_number or order.assigned_counter_number in ("", "UNASSIGNED"):
                raise ValueError(f"Order #{order.order_number} has not been assigned to a counter.")
            if order.assigned_counter_number != counter_number:
                raise ValueError(
                    f"Order #{order.order_number} is assigned to Counter {order.assigned_counter_number}, not Counter {counter_number}."
                )

        # Do not allow resetting cancelled or refunded orders
        if order.payment_status == "REFUNDED" or order.verification_status == "CANCELLED":
            raise ValueError(
                f"Cannot reset order #{order.order_number} with status {order.verification_status} / payment {order.payment_status}."
            )

        order.is_verified_by_cashier = False
        order.verification_status = "IN_PROGRESS"
        order.verification_duration_seconds = None
        for itm in order.items:
            itm.verified_quantity = 0

        await db.commit()
        await db.refresh(order)
        return await self._build_order_detail(db, order)

    async def get_analytics(self, db: AsyncSession) -> AdminAnalyticsResponse:
        """Computes comprehensive live POS analytics for manager view."""
        today_start = datetime.combine(date.today(), datetime.min.time())

        # Overall System-Wide Total Revenue (All counters, all-time, paid only, excluding refunded/cancelled)
        total_rev_stmt = select(
            func.coalesce(func.sum(Order.total_amount), 0.0)
        ).where(
            Order.payment_status == "PAID",
            Order.verification_status != "CANCELLED"
        )
        total_rev_res = await db.execute(total_rev_stmt)
        total_revenue = total_rev_res.scalar() or 0.0

        # Total sales today (paid only, excluding refunded/cancelled transactions)
        sales_stmt = select(
            func.coalesce(func.sum(Order.total_amount), 0.0),
            func.count(Order.id)
        ).where(
            Order.created_at >= today_start,
            Order.payment_status == "PAID",
            Order.verification_status != "CANCELLED"
        )
        sales_res = await db.execute(sales_stmt)
        total_sales, today_orders = sales_res.one()

        # Verified today
        verif_stmt = select(
            func.count(Order.id),
            func.coalesce(func.avg(Order.verification_duration_seconds), 17.0)
        ).where(
            Order.is_verified_by_cashier == True,
            Order.payment_status == "PAID",
            Order.verification_status != "CANCELLED"
        )
        verif_res = await db.execute(verif_stmt)
        verified_count, avg_duration = verif_res.one()

        # Active queue across store
        queue_stmt = select(func.count(QueueTicket.id)).where(
            QueueTicket.status.in_(["WAITING", "PROCESSING"])
        )
        queue_res = await db.execute(queue_stmt)
        queue_count = queue_res.scalar() or 0

        # Discrepancies count (orders with status FLAGGED)
        flag_stmt = select(func.count(Order.id)).where(Order.verification_status == "FLAGGED")
        flag_res = await db.execute(flag_stmt)
        flag_count = flag_res.scalar() or 0

        # Counter by counter summary with counter revenue
        c_stmt = select(Counter).where(Counter.is_active == True)
        c_res = await db.execute(c_stmt)
        counters = c_res.scalars().all()
        counters_overview = []
        for c in counters:
            c_rev_stmt = select(
                func.coalesce(func.sum(Order.total_amount), 0.0)
            ).where(
                Order.assigned_counter_number == c.counter_number,
                Order.payment_status == "PAID",
                Order.verification_status != "CANCELLED"
            )
            c_rev = (await db.execute(c_rev_stmt)).scalar() or 0.0

            c_waiting_stmt = select(func.count(Order.id)).where(
                Order.assigned_counter_number == c.counter_number,
                Order.is_verified_by_cashier == False,
                Order.payment_status == "PAID",
                Order.verification_status != "CANCELLED"
            )
            c_waiting = (await db.execute(c_waiting_stmt)).scalar() or 0

            counters_overview.append({
                "counter_number": c.counter_number,
                "name": c.name,
                "is_express": c.is_express,
                "avg_throughput": round(42.0 * c.avg_scan_speed_factor, 1),
                "is_active": c.is_active,
                "counter_revenue": round(float(c_rev), 2),
                "waiting_orders": int(c_waiting)
            })

        return AdminAnalyticsResponse(
            today_sales_total=round(float(total_sales), 2),
            total_revenue=round(float(total_revenue), 2),
            today_orders_count=int(today_orders),
            today_verified_count=int(verified_count),
            avg_verification_seconds=round(float(avg_duration), 1),
            flagged_discrepancies_count=int(flag_count),
            active_queue_length=int(queue_count),
            counters_overview=counters_overview
        )

    async def get_transactions(
        self,
        db: AsyncSession,
        counter_number: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[AdminTransactionSummary]:
        """Returns paginated, searchable transactions ledger."""
        stmt = select(Order).order_by(desc(Order.created_at))

        if counter_number:
            stmt = stmt.where(Order.assigned_counter_number == counter_number)

        if status_filter:
            sf = status_filter.upper()
            if sf in ("VERIFIED", "CLEARED"):
                stmt = stmt.where(
                    Order.is_verified_by_cashier == True,
                    Order.payment_status != "REFUNDED"
                )
            elif sf == "PENDING":
                stmt = stmt.where(
                    Order.is_verified_by_cashier == False,
                    Order.payment_status != "REFUNDED"
                )
            elif sf == "FLAGGED":
                stmt = stmt.where(Order.verification_status == "FLAGGED")
            elif sf == "REFUNDED":
                stmt = stmt.where(Order.payment_status == "REFUNDED")

        if search:
            s = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Order.order_number.ilike(s),
                    Order.customer_identifier.ilike(s)
                )
            )

        stmt = stmt.offset(skip).limit(limit)
        res = await db.execute(stmt)
        orders = res.scalars().all()

        results = []
        for o in orders:
            items_list = [
                AdminItemVerificationState(
                    product_barcode=itm.product_barcode,
                    product_name=itm.product_name,
                    expected_quantity=itm.quantity,
                    verified_quantity=itm.verified_quantity or 0,
                    is_matched=(itm.verified_quantity or 0) >= itm.quantity,
                    unit_price=itm.unit_price,
                    total_price=itm.total_price,
                    icon="📦"
                )
                for itm in o.items
            ]
            results.append(
                AdminTransactionSummary(
                    order_number=o.order_number,
                    customer_identifier=o.customer_identifier,
                    total_amount=o.total_amount,
                    items_count=len(o.items),
                    payment_method=o.payment_method,
                    payment_status=o.payment_status,
                    verification_status=o.verification_status or ("CLEARED" if o.is_verified_by_cashier else "PENDING"),
                    assigned_counter_number=o.assigned_counter_number,
                    verification_duration_seconds=o.verification_duration_seconds,
                    created_at=o.created_at,
                    items=items_list
                )
            )
        return results


admin_service = AdminService()
