from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.models.queue import QueueTicket
from app.models.counter import Counter
from app.schemas.queue import (
    QueueTicketCreate,
    QueueTicketRead,
    QueueAllocationResponse
)
from app.schemas.ws import WebSocketMessage
from app.services.queue_service import queue_service
from app.services.websocket_manager import ws_manager

router = APIRouter(prefix="/queue", tags=["Queue"])


@router.post("/allocate", response_model=QueueAllocationResponse)
async def allocate_counter(
    payload: QueueTicketCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    'Find Counter' AI Endpoint:
    Calculates the shortest expected wait time based on item count and cashier throughput,
    assigns the optimal counter, and issues a live Queue Ticket.
    """
    try:
        allocation = await queue_service.allocate_optimal_counter(
            session=db,
            customer_name=payload.customer_name,
            items_count=payload.items_count
        )
        await db.commit()

        # Real-time WebSocket broadcast to that counter
        await ws_manager.broadcast_to_channel(
            f"counter:{allocation.assigned_counter_number}",
            WebSocketMessage(
                event="QUEUE_TICKET_ADDED",
                counter_number=allocation.assigned_counter_number,
                data={
                    "ticket_number": allocation.ticket_number,
                    "customer_name": payload.customer_name,
                    "items_count": payload.items_count,
                    "est_wait": f"~{allocation.estimated_wait_minutes}m"
                }
            )
        )

        return allocation
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/counter/{counter_number}", response_model=List[QueueTicketRead])
async def get_counter_queue(
    counter_number: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve all active queue tickets for a specific counter POS terminal."""
    stmt = (
        select(QueueTicket)
        .join(Counter)
        .where(
            Counter.counter_number == counter_number,
            QueueTicket.status.in_(["WAITING", "PROCESSING"])
        )
        .order_by(QueueTicket.created_at.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()
