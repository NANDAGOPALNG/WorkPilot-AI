from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    question: str = Field(..., max_length=1000)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question must not be empty.")
        return v


class Source(BaseModel):
    ref: int                # the [n] number used in the answer text
    document_id: str
    filename: str
    chunk_id: str
    chunk_index: int
    similarity: float
    content: str
    cited: bool             # True if the answer actually references this source


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]
    metadata: dict
