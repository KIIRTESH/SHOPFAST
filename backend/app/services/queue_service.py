from typing import List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.counter import Counter
from app.models.queue import QueueTicket
from app.core.config import settings
from app.schemas.queue import QueueAllocationResponse
import uuid


class QueueService:
    @staticmethod
    async def get_counter_load(session: AsyncSession, counter: Counter) -> Tuple[int, int, float]:
        """
        Calculates (active_customers_in_line, total_items_in_line, estimated_wait_seconds)
        for a given counter based on active queue tickets.
        """
        stmt = (
            select(
                func.count(QueueTicket.id),
                func.coalesce(func.sum(QueueTicket.items_count), 0)
            )
            .where(
                QueueTicket.counter_id == counter.id,
                QueueTicket.status.in_(["WAITING", "PROCESSING"])
            )
        )
        result = await session.execute(stmt)
        customer_count, items_count = result.first() or (0, 0)
        
        # Mathematical estimation model:
        # Time = (Sum of items * base_scan_time / efficiency) + (Number of customers * payment_time)
        scan_time = (items_count * settings.BASE_ITEM_SCAN_SECONDS) / max(0.1, counter.avg_scan_speed_factor)
        payment_time = customer_count * settings.BASE_PAYMENT_SECONDS
        total_wait_sec = scan_time + payment_time

        return int(customer_count), int(items_count), float(total_wait_sec)

    @staticmethod
    async def allocate_optimal_counter(
        session: AsyncSession, 
        customer_name: str, 
        items_count: int
    ) -> QueueAllocationResponse:
        """
        Core FASTSHOP AI Queue Allocation Algorithm:
        1. Queries all active counters.
        2. Filters express eligibility if items_count <= 5.
        3. Chooses counter that minimizes total expected wait time for the customer.
        4. Issues and persists a new QueueTicket.
        """
        stmt = select(Counter).where(Counter.is_active == True)
        result = await session.execute(stmt)
        active_counters = result.scalars().all()

        if not active_counters:
            raise ValueError("No active checkout counters available in store.")

        best_counter: Optional[Counter] = None
        min_estimated_wait = float("inf")
        best_queue_position = 1

        is_express_candidate = (items_count <= settings.EXPRESS_LANE_MAX_ITEMS)

        for counter in active_counters:
            # If counter is designated express only and customer has excessive items, skip
            if counter.is_express and not is_express_candidate:
                continue

            cust_count, items_in_line, wait_sec = await QueueService.get_counter_load(session, counter)

            # Check capacity
            if cust_count >= counter.max_queue_capacity:
                continue

            # Prioritize dedicated express lane for small basket sizes if available
            adjusted_wait = wait_sec
            if counter.is_express and is_express_candidate:
                adjusted_wait *= 0.8  # Express lane priority weight

            if adjusted_wait < min_estimated_wait:
                min_estimated_wait = adjusted_wait
                best_counter = counter
                best_queue_position = cust_count + 1

        # Fallback if all preferred lanes were full
        if not best_counter:
            best_counter = active_counters[0]
            cust_count, _, fallback_wait = await QueueService.get_counter_load(session, best_counter)
            min_estimated_wait = fallback_wait
            best_queue_position = cust_count + 1

        # Ensure min_estimated_wait is always a finite float for valid JSON serialization
        if min_estimated_wait == float("inf") or min_estimated_wait is None:
            min_estimated_wait = 60.0

        # Generate ticket
        ticket_number = f"Q-{uuid.uuid4().hex[:4].upper()}"
        ticket = QueueTicket(
            ticket_number=ticket_number,
            customer_name=customer_name,
            counter_id=best_counter.id,
            items_count=items_count,
            estimated_wait_seconds=round(min_estimated_wait, 1),
            status="WAITING"
        )
        session.add(ticket)
        await session.flush()

        minutes = round(min_estimated_wait / 60.0, 1)
        
        instructions = f"Proceed to Counter {best_counter.counter_number}. Your queue position is #{best_queue_position}."
        if best_counter.is_express:
            instructions += " (Express Fast-Lane)"

        return QueueAllocationResponse(
            ticket_number=ticket_number,
            assigned_counter_number=best_counter.counter_number,
            counter_name=best_counter.name,
            queue_position=best_queue_position,
            estimated_wait_seconds=round(min_estimated_wait, 1),
            estimated_wait_minutes=minutes,
            is_express=best_counter.is_express,
            instructions=instructions
        )


queue_service = QueueService()
