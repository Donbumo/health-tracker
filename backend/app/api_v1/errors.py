from flask import g, jsonify


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def success(data, *, status=200, extra_meta: dict | None = None):
    meta = {"api_version": "1", "request_id": g.request_id}
    if extra_meta:
        meta.update(extra_meta)
    return jsonify(data=data, meta=meta), status


def failure(code: str, message: str, status: int, details: dict | None = None):
    response = jsonify(
        error={"code": code, "message": message, "details": details or {}},
        meta={"api_version": "1", "request_id": g.request_id},
    )
    response.status_code = status
    if status == 401:
        response.headers["WWW-Authenticate"] = 'Bearer realm="health-tracker-api"'
    return response
