from pydantic import BaseModel, ConfigDict, Field


class AdminLoginSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
