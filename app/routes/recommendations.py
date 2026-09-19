from __future__ import annotations

from flask import Blueprint, request

from app.extensions import limiter, specialty_search_key
from app.services.recommendations import recommend_specialties
from app.utils.responses import ok

bp = Blueprint("recommendations", __name__, url_prefix="/api")


@bp.post("/recommend/specialty")
@bp.post("/symptoms/recommend")
@limiter.limit("20 per minute; 200 per hour", key_func=specialty_search_key)
def recommend_specialty_route():
    data = request.get_json(silent=True) or {}
    result = recommend_specialties(data.get("problem", ""), data.get("symptoms", []), data.get("answers"))
    result["recommended_specialties"] = [s["name"] for s in result.get("specialties", [])]
    result["reasoning"] = result.get("message")
    result["emergency_warning"] = result.get("message") if result.get("emergency") else None
    return ok(result, "Specialty recommendation")