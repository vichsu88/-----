from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderItemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=160)
    price: int | None = Field(default=None, ge=0, le=10_000_000)
    qty: int = Field(ge=1, le=999)
    variant: str | None = Field(default=None, max_length=120)
    variantName: str | None = Field(default=None, max_length=120)
    cartId: str | None = Field(default=None, max_length=240)


class OrderCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    orderType: Literal["shop", "donation", "fund", "committee"] = "shop"
    items: list[OrderItemSchema] = Field(min_length=1, max_length=50)
    total: int | None = Field(default=None, ge=0, le=100_000_000)
    shippingFee: int | None = Field(default=None, ge=0, le=10_000)
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    address: str = Field(default="", max_length=300)
    last5: str = Field(default="", max_length=12)
    lunarBirthday: str = Field(default="", max_length=80)
    prayer: str = Field(default="", max_length=500)
    shippingMethod: Literal["home", "711"] = "home"
    storeInfo: str = Field(default="", max_length=300)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value):
        if not value:
            return value
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Email format is invalid")
        return value


class ResendEmailSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(default="", max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value):
        if not value:
            return value
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Email format is invalid")
        return value


class ShipOrderSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trackingNumber: str = Field(min_length=1, max_length=80)
