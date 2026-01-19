from llama_index.core.bridge.pydantic import BaseModel


class DocumentClassifierSchema(BaseModel):
    title: str
    title_confidence: float = 0.0
    tags: list[str]
    tags_confidence: dict[int, float] = {}
    correspondents: list[str]
    correspondents_confidence: dict[int, float] = {}
    document_types: list[str]
    document_types_confidence: dict[int, float] = {}
    storage_paths: list[str]
    storage_paths_confidence: dict[int, float] = {}
    dates: list[str]
