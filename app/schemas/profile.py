import uuid

from pydantic import BaseModel, Field

SEVERITY_LEVELS = {"mild", "moderate", "severe"}


class ProfileAllergenIn(BaseModel):
    allergen_group_id: uuid.UUID
    severity: str = Field(default="moderate")


class ProfileCreate(BaseModel):
    profile_name: str = Field(min_length=1, max_length=100)
    is_default: bool = False
    allergens: list[ProfileAllergenIn] = Field(default_factory=list)
    additive_ingredient_ids: list[uuid.UUID] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    profile_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_default: bool | None = None


class ProfileAllergenOut(BaseModel):
    allergen_group_id: uuid.UUID
    code: str
    severity: str


class ProfileOut(BaseModel):
    profile_id: uuid.UUID
    profile_name: str
    is_default: bool
    allergens: list[ProfileAllergenOut] = Field(default_factory=list)
    additive_ingredient_ids: list[uuid.UUID] = Field(default_factory=list)
