from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DocumentType = Literal["incident_report", "technical_summary"]


class GeneratedDocumentCreate(BaseModel):
    title: str = Field(..., max_length=200)
    document_type: DocumentType
    description: str = Field(..., max_length=10000)  # the source notes
    context: str | None = Field(default=None, max_length=10000)  # symptoms, actions taken, resolution...
    related_ticket_id: UUID | None = None

    @field_validator("title", "description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("context")
    @classmethod
    def _context(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else v


class GeneratedDocumentOut(BaseModel):
    id: str
    title: str
    document_type: str
    content: str
    related_ticket_id: str | None = None
    created_at: str


class GeneratedDocumentSummary(BaseModel):
    id: str
    title: str
    document_type: str
    related_ticket_id: str | None = None
    created_at: str


class GeneratedDocumentList(BaseModel):
    documents: list[GeneratedDocumentSummary]
    count: int
