"""Flask extension instances."""

from flask_cors import CORS
from flask_jwt_extended import JWTManager, decode_token
from flask_limiter import Limiter
from flask import request
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

def rate_limit_key() -> str:
    """Return a fair, endpoint-aware key without trusting client-provided identity data.

    Authenticated requests are isolated by user and role. Public discovery/search
    traffic is isolated by origin IP plus a normalized specialty filter, preventing
    a single specialty from exhausting the search allowance for everyone else.
    """
    auth = request.headers.get("Authorization", "")
    client_ip = get_remote_address()
    specialty_id = (request.args.get("specialty_id") or request.view_args.get("specialty_id") if request.view_args else request.args.get("specialty_id"))
    specialty_id = str(specialty_id or "all").strip()[:40]

    if auth.startswith("Bearer "):
        # Decode the signed token only to isolate one authenticated account from
        # another. Invalid tokens deliberately fall back to IP-based throttling.
        try:
            user_id = decode_token(auth.removeprefix("Bearer "), allow_expired=True).get("sub")
        except Exception:
            user_id = None
        if user_id:
            return f"user:{user_id}:{request.endpoint or 'api'}"
    return f"public:{client_ip}:{request.endpoint or 'api'}:specialty:{specialty_id}"


def specialty_search_key() -> str:
    """Rate-limit public doctor discovery separately for each specialty filter."""
    return f"{get_remote_address()}:specialty:{(request.args.get('specialty_id') or 'all').strip()[:40]}"


db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
jwt = JWTManager()
cors = CORS()
limiter = Limiter(key_func=rate_limit_key, default_limits=["300 per hour"])
migrate = Migrate()
