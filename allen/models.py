from typing import Literal, Optional

from pydantic import BaseModel, Field

OutputKind = Literal["content", "ad", "post", "newsletter", "book"]


# ---- platform: projects + namespaced memory ----
class CreateProjectRequest(BaseModel):
    name: str
    namespace: str


class MemoryRequest(BaseModel):
    content: str
    brand: Optional[str] = None


class MemoryUpdateRequest(BaseModel):
    content: str


class DraftRequest(BaseModel):
    brand: str = Field(..., description="Brand key, e.g. 'com', 'vlog'")
    topic: str = Field(..., description="Topic or brief to write from")
    persona: Optional[str] = Field(None, description="Speaking persona, e.g. 'Coach Rahm'")
    output_kind: OutputKind = "post"
    allie_context: Optional[str] = Field(None, description="Grounding context/research from ALLIE")
    write_doc: bool = Field(True, description="Write the draft to Google Docs for review")
    brand_examples: Optional[list[str]] = Field(None, description="Previously approved scripts for this brand — used as few-shot style reference")


class DraftResponse(BaseModel):
    brand: str
    persona: Optional[str]
    output_kind: OutputKind
    title: str
    script: str
    doc_url: Optional[str] = None
    doc_id: Optional[str] = None
    model: str


class DirectRequest(BaseModel):
    script: str
    brand: str
    persona: Optional[str] = None
    intensity: Optional[str] = None
    stability_mode: Optional[str] = None  # creative | natural | robust (override)
    brand_examples: Optional[list[str]] = Field(None, description="Previously tagged scripts for this brand — used as style reference for the emotion director")


class DirectResponse(BaseModel):
    tagged_script: str
    stability_mode: str
    stability: float
    audio_tag_palette: str


class MeetingRequest(BaseModel):
    transcript: str
    brand: Optional[str] = None


class MeetingResponse(BaseModel):
    summary: str = ""
    action_items: list[str] = []
    highlights: list[str] = []


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    brand: Optional[str] = None
    persona: Optional[str] = None
    history: list[ChatMessage] = []
    context: Optional[str] = None  # concierge context: system state, recent work, memories
    max_tokens: int = 600


class ChatResponse(BaseModel):
    reply: str


class TopicsRequest(BaseModel):
    brand: str
    count: int = 6
    context: Optional[str] = None


class TopicSuggestion(BaseModel):
    title: str
    hook: str = ""
    angle: str = ""


class TopicsResponse(BaseModel):
    topics: list[TopicSuggestion] = []


class MetadataRequest(BaseModel):
    brand: str
    platform: str
    topic: str = ""
    persona: Optional[str] = None
    script: Optional[str] = None


class MetadataResponse(BaseModel):
    title: str = ""
    caption: str = ""
    hashtags: list[str] = []
    first_comment: str = ""
    audience: str = ""


class SpeakRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None
    model_id: Optional[str] = None  # e.g. "eleven_v3" for audio tags
    stability: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    service: str = "allen"
    checks: dict[str, str]
