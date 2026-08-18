"""Shared response envelopes and primitives."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class PageParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class OkResponse(BaseModel):
    ok: bool = True


class IdResponse(BaseModel):
    id: uuid.UUID


class LocalizedText(BaseModel):
    uz: str
    ru: str | None = None
    en: str | None = None

    def get(self, locale: str) -> str:
        return getattr(self, locale, None) or self.uz


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str
    # Surfaced so deployments can be audited against the data-residency requirement.
    data_residency_region: str
    database: str
    time: datetime
