from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from utils.timezone import format_taipei


FeedbackStatus = Literal["pending", "approved", "sent"]


def _stringify_id(value):
    return "" if value is None else str(value)


def _clean_category(value):
    """統一回饋分類格式，避免 Controller 重複清理 list[str]。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("category must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


class FeedbackCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nickname: str = Field(default="", max_length=80)
    category: list[str] = Field(default_factory=list, max_length=10)
    content: str = Field(min_length=1, max_length=2000)
    agreed: bool

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value):
        return _clean_category(value)

    @field_validator("agreed")
    @classmethod
    def require_agreement(cls, value):
        if value is not True:
            raise ValueError("必須同意回饋規範")
        return value


class FeedbackUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nickname: str | None = Field(default=None, min_length=1, max_length=80)
    category: list[str] | None = Field(default=None, max_length=10)
    content: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value):
        if value is None:
            return None
        return _clean_category(value)

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少需要提供一個更新欄位")
        return self


class FeedbackStatusQuerySchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    status: FeedbackStatus | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=100)


class FeedbackApproveSchema(BaseModel):
    """目前 approve API 無 body；保留空 Schema 讓 Controller 維持一致驗證流程。"""

    model_config = ConfigDict(extra="forbid")


class FeedbackShipSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trackingNumber: str = Field(min_length=1, max_length=80)


class FeedbackRejectSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(default="", max_length=500)


class FeedbackActionResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    message: str = ""
    feedbackId: str = ""


class FeedbackPublicResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(default="", alias="_id")
    feedbackId: str = ""
    nickname: str = ""
    category: list[str] = Field(default_factory=list)
    content: str = ""
    createdAt: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def stringify_id(cls, value):
        return _stringify_id(value)

    @field_validator("createdAt", mode="before")
    @classmethod
    def format_created_at(cls, value):
        if isinstance(value, datetime):
            return format_taipei(value, "%Y-%m-%d")
        return "" if value is None else str(value)


class FeedbackUserListItemResponseSchema(FeedbackPublicResponseSchema):
    status: FeedbackStatus = "pending"
    content_preview: str = ""
    trackingNumber: str = ""

    @model_validator(mode="after")
    def fill_content_preview(self):
        if not self.content_preview and self.content:
            self.content_preview = self.content[:50] + ("..." if len(self.content) > 50 else "")
        return self


class FeedbackAdminResponseSchema(FeedbackPublicResponseSchema):
    lineId: str = ""
    status: FeedbackStatus = "pending"
    realName: str = ""
    phone: str = ""
    address: str = ""
    email: str = ""
    lunarBirthday: str = ""
    has_received: bool = False
    approvedAt: str = ""
    approvedBy: str = ""
    sentAt: str = ""
    sentBy: str = ""
    trackingNumber: str = ""
    isMarked: bool = False

    @field_validator("createdAt", mode="before")
    @classmethod
    def format_admin_created_at(cls, value):
        if isinstance(value, datetime):
            return format_taipei(value, "%Y-%m-%d %H:%M:%S")
        return "" if value is None else str(value)

    @field_validator("approvedAt", "sentAt", mode="before")
    @classmethod
    def format_admin_datetime(cls, value):
        if isinstance(value, datetime):
            return format_taipei(value)
        return "" if value is None else str(value)
