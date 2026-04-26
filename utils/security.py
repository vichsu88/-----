import re

from flask import jsonify, request


class SecurityValidationError(ValueError):
    pass


MONGO_OPERATOR_PATTERN = re.compile(r'(^\$)|(\.)|(\x00)')
QUERY_OPERATOR_PATTERN = re.compile(r'(\$)|(\[)|(\])|(\.)|(\x00)')


def validate_no_mongo_operators(value, path='json'):
    """Reject JSON keys that could be interpreted as MongoDB operators or paths."""
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or MONGO_OPERATOR_PATTERN.search(key):
                raise SecurityValidationError(f"Invalid key at {path}")
            validate_no_mongo_operators(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_no_mongo_operators(child, f"{path}[{index}]")


def validate_request_input():
    """Flask before_request hook for NoSQL injection payload shapes."""
    for key in request.args.keys():
        if QUERY_OPERATOR_PATTERN.search(key):
            return jsonify({"error": "Invalid query parameter"}), 400

    if request.is_json:
        payload = request.get_json(silent=True)
        if payload is not None:
            try:
                validate_no_mongo_operators(payload)
            except SecurityValidationError:
                return jsonify({"error": "Invalid JSON payload"}), 400
    return None


def get_json_object(default=None):
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {} if default is None else default


def get_json_value(default=None):
    data = request.get_json(silent=True)
    if data is None:
        return default
    return data


def as_string(value, default=''):
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def safe_regex_contains(value, max_length=80):
    text = as_string(value).strip()
    if not text:
        return None
    return re.escape(text[:max_length])
