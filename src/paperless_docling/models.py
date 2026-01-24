from typing import Any

from pydantic import BaseModel
from pydantic import Field


class BoundingBox(BaseModel):
    left: float = Field(alias="l")
    top: float = Field(alias="t")
    right: float = Field(alias="r")
    bottom: float = Field(alias="b")
    coord_origin: str = Field(default="BOTTOMLEFT")

    def to_normalized_origin_bottom_left(
        self,
        page_width: float,
        page_height: float,
    ) -> "BoundingBox":
        """
        Convert to strictly bottom-left origin normalized coordinates (0-1 or 0-page_dim).
        Paperless/ReportLab usually expects bottom-left for PDF generation.
        Docling often returns BOTTOMLEFT, so we might just need to pass it through,
        but if it's TOPLEFT, we flip Y.
        """
        if self.coord_origin == "BOTTOMLEFT":
            return self
        elif self.coord_origin == "TOPLEFT":
            return BoundingBox(
                l=self.left,
                t=page_height - self.bottom,  # Top becomes bottom-relative top
                r=self.right,
                b=page_height - self.top,  # Bottom becomes bottom-relative bottom
                coord_origin="BOTTOMLEFT",
            )
        return self


class Size(BaseModel):
    width: float
    height: float


class PageItem(BaseModel):
    size: Size
    page_no: int


class ProvenanceItem(BaseModel):
    page_no: int
    bbox: BoundingBox
    charspan: list[int] = Field(default_factory=list)


class DocItem(BaseModel):
    self_ref: Any
    parent: Any = None
    children: list[Any] = Field(default_factory=list)
    crefs: list[Any] = Field(default_factory=list)
    label: str  # e.g. "text", "heading", "table"
    prov: list[ProvenanceItem] = Field(default_factory=list)
    text: str | None = None


class DoclingDocument(BaseModel):
    model_config = {"extra": "ignore"}

    schema_name: str | None = Field(alias="$schema", default=None)
    version: str | None = None
    name: str = "document"
    pages: dict[str, PageItem] = Field(default_factory=dict)
    texts: list[DocItem] = Field(default_factory=list)
    tables: list[DocItem] = Field(default_factory=list)
    pictures: list[DocItem] = Field(default_factory=list)
    headings: list[DocItem] = Field(default_factory=list)
    body: Any = None
    groups: list[Any] = Field(default_factory=list)
    key_value_items: list[Any] = Field(default_factory=list)
    form_items: list[Any] = Field(default_factory=list)


class ServerDocumentResponse(BaseModel):
    filename: str | None = None
    md_content: str | None = None
    json_content: DoclingDocument | None = None
    html_content: str | None = None
    text_content: str | None = None


class DoclingServerResult(BaseModel):
    # This structure matches the Docling-serve result
    document: ServerDocumentResponse
    status: str | None = None
    errors: list[Any] = Field(default_factory=list)
