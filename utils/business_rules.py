import os


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


SHOP_SHIPPING_FEES = {
    "711": _env_int("SHOP_SHIPPING_711_FEE", 60),
    "home": _env_int("SHOP_SHIPPING_HOME_FEE", 120),
}

ORDER_PAYMENT_DEADLINE_HOURS = _env_int("ORDER_PAYMENT_DEADLINE_HOURS", 2)
UNPAID_ORDER_GRACE_HOURS = _env_int("UNPAID_ORDER_GRACE_HOURS", 76)
SHIPPED_ORDER_RETENTION_DAYS = _env_int("SHIPPED_ORDER_RETENTION_DAYS", 14)


def get_shop_shipping_fee(shipping_method):
    return SHOP_SHIPPING_FEES[shipping_method]
