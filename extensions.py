from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()
limiter = Limiter(
    get_remote_address,
    default_limits=["3000 per day", "1000 per hour"],
    storage_uri="memory://"
)
