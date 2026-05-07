from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.timezone import format_taipei


def _stringify_id(value):
    return "" if value is None else str(value)


def _format_datetime(value):
    if isinstance(value, datetime):
        return format_taipei(value)
    return "" if value is None else str(value)


class UserCreateSchema(BaseModel):
    """LINE 登入建立使用者時的資料契約。"""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    lineId: str = Field(min_length=1, max_length=128)
    displayName: str = Field(default="", max_length=120)
    pictureUrl: str = Field(default="", max_length=500)
    statusMessage: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value):
        if value and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            raise ValueError("Email format is invalid")
        return value


class UserProfileUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    realName: str = Field(min_length=1, max_length=80)
    nickname: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    address: str = Field(default="", max_length=300)
    lunarBirthday: str = Field(default="", max_length=80)
    birthTime: str = Field(default="吉時", max_length=40)
    gender: str = Field(default="", max_length=20)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value):
        if value and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            raise ValueError("Email format is invalid")
        return value


class UserProfileResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(default="", alias="_id")
    lineId: str = ""
    displayName: str = ""
    pictureUrl: str = ""
    realName: str = ""
    nickname: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    lunarBirthday: str = ""
    birthTime: str = ""
    gender: str = ""
    title: str = ""
    has_received_gift: bool = False
    createdAt: str = ""
    updatedAt: str = ""
    lastLoginAt: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def stringify_id(cls, value):
        return _stringify_id(value)

    @field_validator("createdAt", "updatedAt", "lastLoginAt", mode="before")
    @classmethod
    def format_datetimes(cls, value):
        return _format_datetime(value)


class CurrentUserResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    logged_in: bool
    user: UserProfileResponseSchema | None = None


class UserProfileUpdateResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    message: str = ""


class UserMemberListQuerySchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    q: str = Field(default="", max_length=80)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=100)


class UserMemberListItemResponseSchema(UserProfileResponseSchema):
    orderCount: int = Field(default=0, ge=0)
    donationTotal: int = Field(default=0, ge=0)
