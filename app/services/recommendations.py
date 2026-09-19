from __future__ import annotations

from app.models import Specialty, SymptomRule

DISCLAIMER = "This tool provides general specialty guidance and is not a medical diagnosis."
EMERGENCY_MESSAGE = "Emergency warning: symptoms may require immediate emergency care. Please seek urgent medical help instead of booking a routine appointment."

DEFAULT_RULES = {
    "headache": "Neurology",
    "chest pain": "Cardiology",
    "stomach pain": "Gastroenterology",
    "skin": "Dermatology",
    "rash": "Dermatology",
    "eye": "Ophthalmology",
    "ear": "ENT",
    "joint": "Orthopedics",
    "bone": "Orthopedics",
    "fever": "General Medicine",
    "breathing": "Pulmonology",
    "dental": "Dentistry",
    "women": "Gynecology",
    "child": "Pediatrics",
    "urinary": "Urology",
    "mental": "Psychiatry",
}

EMERGENCY_KEYWORDS = ["severe chest pain", "severe breathing", "stroke", "face drooping", "severe bleeding", "loss of consciousness", "allergic reaction", "anaphylaxis"]


def recommend_specialties(problem: str, symptoms: list[str] | None = None, answers: dict | None = None):
    text = " ".join([problem or "", *(symptoms or []), *(str(v) for v in (answers or {}).values())]).lower()
    if any(k in text for k in EMERGENCY_KEYWORDS):
        return {"disclaimer": DISCLAIMER, "emergency": True, "message": EMERGENCY_MESSAGE, "specialties": []}

    specialty_names: set[str] = set()
    db_rules = SymptomRule.query.all()
    for rule in db_rules:
        if rule.keyword.lower() in text:
            if rule.emergency:
                return {"disclaimer": DISCLAIMER, "emergency": True, "message": rule.message or EMERGENCY_MESSAGE, "specialties": []}
            if rule.specialty:
                specialty_names.add(rule.specialty.name)

    for keyword, specialty in DEFAULT_RULES.items():
        if keyword in text:
            specialty_names.add(specialty)

    specialties = Specialty.query.filter(Specialty.name.in_(specialty_names), Specialty.is_active.is_(True)).all() if specialty_names else []
    return {"disclaimer": DISCLAIMER, "emergency": False, "message": "Recommended specialties based on general symptom guidance.", "specialties": [s.to_dict() for s in specialties]}
