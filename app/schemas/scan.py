import uuid
from datetime import datetime

from pydantic import BaseModel, Field

OCR_ENGINES = {"mlkit_ondevice", "cloud_vision"}
PLATFORMS = {"android", "ios"}
# Must match kb.languages (sql/00_schema.sql SECTION 5.1). Drives which
# kb.ingredient_translations row app.fn_scan_summary returns.
LANGUAGES = {"en", "si", "ta"}


class ProductIn(BaseModel):
    product_name: str = Field(min_length=1, max_length=250)
    brand_name: str | None = Field(default=None, max_length=200)
    barcode: str | None = Field(default=None, max_length=50)


class ScanCreate(BaseModel):
    profile_id: uuid.UUID | None = None
    raw_ocr_text: str = Field(min_length=1)
    # Client already split the OCR block into individual ingredient strings
    # (proposal §6.3 step 5, "text cleaning and parsing"). The server does
    # NOT re-parse raw_ocr_text — it trusts this list and matches each entry.
    ingredients: list[str] = Field(min_length=1)
    ocr_confidence: float = Field(ge=0, le=100)
    ocr_engine: str = "mlkit_ondevice"
    device_platform: str | None = None
    product: ProductIn | None = None
    # Language for the returned findings' display_name / explanation. The
    # scan itself is language-neutral; only the summary is localised.
    language: str = "en"

    def validate_enums(self) -> None:
        if self.ocr_engine not in OCR_ENGINES:
            raise ValueError(f"ocr_engine must be one of {OCR_ENGINES}")
        if self.device_platform is not None and self.device_platform not in PLATFORMS:
            raise ValueError(f"device_platform must be one of {PLATFORMS}")
        if self.language not in LANGUAGES:
            raise ValueError(f"language must be one of {LANGUAGES}")


class ScanSummaryOut(BaseModel):
    """Mirrors the JSON shape returned by app.fn_scan_summary() verbatim,
    plus a couple of fields the DB function doesn't include."""

    scan_id: uuid.UUID
    scanned_at: datetime
    ocr_confidence: float
    ocr_engine: str
    total_parsed: int
    unmatched: int
    findings: list[dict]


class ScanListItemOut(BaseModel):
    scan_id: uuid.UUID
    scanned_at: datetime
    status: str
    ocr_confidence: float
