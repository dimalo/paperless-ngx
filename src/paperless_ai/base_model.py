from llama_index.core.bridge.pydantic import BaseModel


class DocumentClassifierSchema(BaseModel):
    title: str
    title_confidence: float = 0.0
    tags: list[str]
    tags_confidence: dict[str, float] = {}
    correspondents: list[str]
    correspondents_confidence: dict[str, float] = {}
    document_types: list[str]
    document_types_confidence: dict[str, float] = {}
    storage_paths: list[str]
    storage_paths_confidence: dict[str, float] = {}
    dates: list[str]
