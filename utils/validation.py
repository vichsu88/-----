from pydantic import ValidationError as PydanticValidationError

from utils.errors import ValidationError


def validate_payload(schema_cls, payload):
    try:
        return schema_cls.model_validate(payload)
    except PydanticValidationError as exc:
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            details.append({
                "field": location,
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            })
        raise ValidationError("Invalid request payload", details=details)
