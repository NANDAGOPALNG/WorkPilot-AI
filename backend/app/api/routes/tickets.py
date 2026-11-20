import logging

from fastapi import APIRouter, HTTPException, Query, Response

from app.core.config import ConfigError
from app.schemas.ticket import TicketCreate, TicketList, TicketOut, TicketPriority, TicketStatus, TicketUpdate
from app.services import ticket_service
from app.services.ticket_service import TicketError

logger = logging.getLogger("workpilot.tickets")
router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _call(fn, *args, **kwargs):
    """Run a ticket_service function and translate its errors into HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except TicketError as exc:
        raise HTTPException(exc.status_code, detail={"message": str(exc)}) from None
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise HTTPException(503, detail={"message": "Server is not configured correctly (see server logs)."}) from None


# Plain `def` routes run in FastAPI's threadpool, so the blocking Supabase calls are fine.
@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketCreate, response: Response):
    """201 with the new ticket. If an identical ticket was just created, returns it with 200 instead."""
    ticket, created = _call(ticket_service.create_ticket, body.model_dump())
    if not created:
        response.status_code = 200
    return ticket


@router.get("", response_model=TicketList)
def list_tickets(
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return _call(ticket_service.list_tickets, status=status, priority=priority, limit=limit, offset=offset)


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str):
    """ticket_id can be the ticket UUID or its number, e.g. TKT-1001."""
    return _call(ticket_service.get_ticket, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: str, body: TicketUpdate):
    return _call(ticket_service.update_ticket, ticket_id, body.model_dump(exclude_none=True))
