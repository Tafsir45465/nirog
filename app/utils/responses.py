from __future__ import annotations

from flask import jsonify


def ok(data=None, message="OK", status=200, **meta):
    payload = {"success": True, "message": message, "data": data}
    if meta:
        payload["meta"] = meta
    return jsonify(payload), status


def error(message="Error", status=400, code=None, details=None):
    payload = {"success": False, "message": message}
    if code:
        payload["code"] = code
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status
