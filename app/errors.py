from __future__ import annotations

from werkzeug.exceptions import HTTPException

from .utils.responses import error


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str | None = None, details=None):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details
        super().__init__(message)


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        return error(exc.message, exc.status_code, exc.code, exc.details)

    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        return error(exc.description or exc.name, exc.code or 500, exc.name)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        if app.config.get("DEBUG"):
            raise exc
        return error("Unexpected server error", 500, "internal_error")
