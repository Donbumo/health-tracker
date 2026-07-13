from functools import wraps

from flask import current_app, g, request

from app.api_v1.auth import parse_access_token
from app.api_v1.errors import ApiError
from app.api_v1.rate_limit import rate_limiter


def bearer_required(view=None, *, allow_revoked: bool = False):
    if view is None:
        return lambda actual_view: bearer_required(actual_view, allow_revoked=allow_revoked)

    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or header.count(" ") != 1:
            raise ApiError("authorization_required", "Se requiere un Bearer token.", 401)
        token = header[7:].strip()
        if not token:
            raise ApiError("authorization_required", "Se requiere un Bearer token.", 401)
        user, api_session, claims = parse_access_token(token, allow_revoked=allow_revoked)
        g.api_user = user
        g.api_session = api_session
        g.api_claims = claims
        rate_limiter.check(
            "authenticated",
            f"{user.id}:{api_session.public_session_id}",
            current_app.config["API_RATE_LIMIT_AUTHENTICATED"],
        )
        return view(*args, **kwargs)

    return wrapped
