from typing import Literal, Optional

from pydantic import BaseModel, Field

OutputKind = Literal["content", "ad", "post", "newsletter", "book"]


class DraftRequest(BaseModel):
    brand: str = Field(..., description="Brand key, e.g. 'com', 'vlog'")
    topic: str = Field(..., description="Topic or brief to write from")
    persona: Optional[str] = Field(None, description="Speaking persona, e.g. 'Coach Rahm'")
    output_kind: OutputKind = "post"
    allie_context: Optional[str] = Field(None, description="Grounding context/research from ALLIE")
    write_doc: bool = Field(True, description="Write the draft to Google Docs for review")


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


class DirectResponse(BaseModel):
    tagged_script: str
    stability_mode: str
    stability: float
    audio_tag_palette: str


class SpeakRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None
    model_id: Optional[str] = None  # e.g. "eleven_v3" for audio tags
    stability: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    service: str = "allen"
    checks: dict[str, str]
