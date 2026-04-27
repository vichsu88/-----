def pick_allowed_fields(data, allowed_fields):
    if not isinstance(data, dict):
        return {}
    return {
        key: data[key]
        for key in allowed_fields
        if key in data
    }
