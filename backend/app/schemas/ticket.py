from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TicketPriority = Literal["low", "medium", "high", "critical"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]


def _strip_required(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class TicketCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="general", max_length=50)
    priority: TicketPriority = "medium"

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _strip_required(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        return v.strip()

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        return v.strip().lower() or "general"


class TicketUpdate(BaseModel):
    """Only these fields can change; anything else (id, ticket_number, timestamps...) is rejected."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return _strip_required(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def _at_least_one(self):
        if all(getattr(self, f) is None for f in ("title", "description", "status", "priority")):
            raise ValueError("Provide at least one of: title, description, status, priority.")
        return self


class TicketOut(BaseModel):
    id: str
    ticket_number: str
    title: str
    description: str
    category: str
    priority: str
    status: str
    created_at: str
    updated_at: str


class TicketList(BaseModel):
    tickets: list[TicketOut]
    count: int
    limit: int
    offset: int
