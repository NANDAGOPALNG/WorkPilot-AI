"""Input schemas, response envelope and provider-independent tool definitions for the agent tool layer.

The tool definitions use plain JSON Schema (name / description / parameters / required). They are
NOT in any provider's wire format. When Agora Conversational AI is integrated, check Agora's
current documentation and convert them with a small adapter.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.generated_document import GeneratedDocumentCreate
from app.schemas.ticket import TicketCreate


# --------------------------------------------------------------------------- inputs
# extra="forbid": the agent can never smuggle in protected fields (id, ticket_number, timestamps...).
class SearchKnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        ..., max_length=1000,
        description="The user's question, phrased as a complete question about company documents or policies.",
    )

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class CreateTicketInput(TicketCreate):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=200, description="Short summary of the problem.")
    description: str = Field(..., min_length=1, max_length=5000, description="What is wrong, in the user's words.")
    category: str = Field(default="general", max_length=50, description="Ticket category, e.g. network, hardware, access, software. Defaults to general.")
    priority: Literal["low", "medium", "high", "critical"] = Field(
        default="medium", description="One of low, medium, high, critical. Defaults to medium."
    )
    confirmed: bool = Field(
        default=False,
        description=(
            "Leave false (default) to only preview the ticket; nothing is created. Set true ONLY after the user "
            "has explicitly confirmed the previewed ticket details."
        ),
    )

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_case(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("description")
    @classmethod
    def _description_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class GetTicketStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id_or_number: str = Field(
        ..., max_length=64, description="Ticket number such as TKT-1001, or the ticket UUID."
    )

    @field_validator("ticket_id_or_number")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class GenerateDocumentInput(GeneratedDocumentCreate):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ response envelope
class ToolError(BaseModel):
    code: str  # validation_error | not_found | not_configured | upstream_error | service_error
    message: str


class ToolSuccess(BaseModel):
    success: Literal[True] = True
    tool: str
    data: dict[str, Any]


class ToolFailure(BaseModel):
    success: Literal[False] = False
    tool: str
    error: ToolError


# ------------------------------------------------------------------ tool definitions
def _parameters(model: type[BaseModel]) -> dict:
    """JSON Schema `parameters` object for a model, without pydantic's noise (titles)."""
    schema = model.model_json_schema()

    def clean(node):
        if isinstance(node, dict):
            # Drop the "title" annotation, but keep a property that is itself named "title".
            return {
                k: ({n: clean(s) for n, s in v.items()} if k == "properties" else clean(v))
                for k, v in node.items() if k != "title"
            }
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return {
        "type": "object",
        "properties": {n: clean(s) for n, s in schema["properties"].items()},
        "required": schema.get("required", []),
    }


TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "search_knowledge",
        "description": (
            "Search company documents and get a grounded answer with source citations. Use for questions about "
            "policies, procedures or internal information. If `found` is false, say the documents do not cover it; "
            "never answer from general knowledge as if it came from company documents."
        ),
        "parameters": _parameters(SearchKnowledgeInput),
    },
    {
        "name": "create_ticket",
        "description": (
            "Create a support ticket. Two-step: first call WITHOUT confirmed to get a preview (nothing is created), "
            "read the title, priority and category back to the user and ask them to confirm. Only after they say yes, "
            "call again with confirmed=true. Tell the user a ticket exists only when the response has "
            "data.created=true, and quote data.ticket.ticket_number from the response."
        ),
        "parameters": _parameters(CreateTicketInput),
    },
    {
        "name": "get_ticket_status",
        "description": (
            "Look up a support ticket by ticket number (e.g. TKT-1001) or UUID and report its current status and details. "
            "If the tool reports not found, tell the user so; do not guess."
        ),
        "parameters": _parameters(GetTicketStatusInput),
    },
    {
        "name": "generate_document",
        "description": (
            "Generate and save an incident report or technical summary from facts the user has provided. Missing "
            "facts are marked 'Not provided' and are never invented. Say the document was saved only when the "
            "response has data.saved=true, and use data.document_id."
        ),
        "parameters": _parameters(GenerateDocumentInput),
    },
]
