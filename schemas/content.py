from datetime import date as date_cls, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from utils.timezone import format_taipei


def _stringify_id(value):
    return "" if value is None else str(value)


def _parse_content_date(value):
    """公告日期是內容日期，不是交易時間；允許 YYYY/MM/DD 與 YYYY-MM-DD。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value or "").strip().replace("/", "-")
    if not text:
        raise ValueError("date is required")
    try:
        return date_cls.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("date must use YYYY/MM/DD or YYYY-MM-DD format") from exc


def _format_content_date(value):
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, date_cls):
        return value.strftime("%Y/%m/%d")
    return "" if value is None else str(value)


def _format_created_at(value):
    if isinstance(value, datetime):
        return format_taipei(value, "%Y-%m-%d")
    return "" if value is None else str(value)


class AnnouncementCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: date_cls
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=5000)
    isPinned: bool = False

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, value):
        return _parse_content_date(value)


class AnnouncementUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: date_cls | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, min_length=1, max_length=5000)
    isPinned: bool | None = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, value):
        if value in (None, ""):
            return None
        return _parse_content_date(value)

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少需要提供一個更新欄位")
        return self


class AnnouncementResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(default="", alias="_id")
    date: str = ""
    title: str = ""
    content: str = ""
    isPinned: bool = False
    createdAt: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def stringify_id(cls, value):
        return _stringify_id(value)

    @field_validator("date", mode="before")
    @classmethod
    def format_date(cls, value):
        return _format_content_date(value)

    @field_validator("createdAt", mode="before")
    @classmethod
    def format_created_at(cls, value):
        return _format_created_at(value)


class AnnouncementListResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    announcements: list[AnnouncementResponseSchema] = Field(default_factory=list)


class FAQQuerySchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    category: str = Field(default="", max_length=40)


class FAQCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=5000)
    category: str = Field(min_length=1, max_length=40, pattern=r"^[\u4e00-\u9fff]+$")
    isPinned: bool = False


class FAQUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str | None = Field(default=None, min_length=1, max_length=300)
    answer: str | None = Field(default=None, min_length=1, max_length=5000)
    category: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[\u4e00-\u9fff]+$")
    isPinned: bool | None = None

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少需要提供一個更新欄位")
        return self


class FAQResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(default="", alias="_id")
    question: str = ""
    answer: str = ""
    category: str = ""
    isPinned: bool = False
    createdAt: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def stringify_id(cls, value):
        return _stringify_id(value)

    @field_validator("createdAt", mode="before")
    @classmethod
    def format_created_at(cls, value):
        return _format_created_at(value)


class FAQListResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    faqs: list[FAQResponseSchema] = Field(default_factory=list)


class ContentActionResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    message: str = ""
