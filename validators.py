"""Server-side validation of a profiling submission.

The wizard validates as you go, but that is for speed of feedback, not for
trust - anything can POST to this API. Rules are read from profile_schema.json so
a question added by the admin portal is validated without a code change.
"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[\d+][\d\s\-()]{6,19}$")

# Steps whose content is checked against the taxonomy rather than the field schema.
SPECIAL_KINDS = {"welcome", "role", "business_services", "value_constructs",
                 "tool_stack", "ratings", "ratings_path", "ratings_battery"}


def validate_submission(payload: dict, schema: dict, tax) -> list[str]:
    """The core submission: details, choices and ratings."""
    errors: list[str] = []
    errors += _validate_fields(payload, schema, stage="core")
    errors += _validate_selections(payload, tax)
    errors += _validate_ratings(payload, tax)
    return errors


def validate_details(payload: dict, schema: dict) -> list[str]:
    """The optional follow-up section.

    Every field in it is optional by design, so this checks shape and format
    only - a half-filled section is a valid thing to save, and refusing it would
    just lose the student's work.
    """
    return _validate_fields(payload, schema, stage="followup")


def _validate_fields(payload: dict, schema: dict, stage: str) -> list[str]:
    errors: list[str] = []
    for phase in schema.get("phases", []):
        if phase.get("stage", "core") != stage:
            continue
        for step in phase.get("steps", []):
            if step.get("kind") in SPECIAL_KINDS:
                continue
            values = payload.get(step["id"], {})
            if not isinstance(values, dict):
                errors.append(f"{step['id']}: expected an object")
                continue
            for field in step.get("fields", []):
                errors += _validate_field(field, values.get(field["id"]), step["id"])
    return errors


def _validate_field(field: dict, value, step_id: str) -> list[str]:
    label = field.get("label") or field["id"]
    where = f"{step_id}.{field['id']}"
    ftype = field.get("type")
    required = field.get("required", False)
    errors: list[str] = []

    if ftype == "repeater":
        entries = value or []
        if not isinstance(entries, list):
            return [f"{where}: expected a list"]
        if field.get("max_items") and len(entries) > field["max_items"]:
            errors.append(f"{label}: at most {field['max_items']} entries")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"{where}[{index}]: expected an object")
                continue
            for sub in field.get("fields", []):
                errors += _validate_field(sub, entry.get(sub["id"]), f"{where}[{index}]")
        return errors

    if _is_blank(value):
        if required:
            errors.append(f"{label} is required")
        return errors

    if ftype == "multiselect":
        if not isinstance(value, list):
            return [f"{label}: expected a list"]
        if field.get("min") and len(value) < field["min"]:
            errors.append(f"{label}: choose at least {field['min']}")
        if field.get("max") and len(value) > field["max"]:
            errors.append(f"{label}: choose at most {field['max']}")
        if field.get("options"):
            unknown = [v for v in value if v not in field["options"]]
            if unknown:
                errors.append(f"{label}: unexpected option {unknown[0]!r}")
        return errors

    if ftype == "select" and field.get("options") and value not in field["options"]:
        errors.append(f"{label}: unexpected option {value!r}")
    elif ftype == "email" and not EMAIL_RE.match(str(value).strip()):
        errors.append(f"{label}: doesn't look like an email address")
    elif ftype == "tel" and not PHONE_RE.match(str(value).strip()):
        errors.append(f"{label}: doesn't look like a phone number")
    elif ftype == "url" and not str(value).strip().lower().startswith(("http://", "https://")):
        errors.append(f"{label}: links need to start with http:// or https://")
    elif ftype == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return [f"{label}: expected a number"]
        if field.get("min") is not None and number < field["min"]:
            errors.append(f"{label}: must be {field['min']} or more")
        if field.get("max") is not None and number > field["max"]:
            errors.append(f"{label}: must be {field['max']} or less")
    elif ftype == "slider_pair":
        try:
            number = int(value)
        except (TypeError, ValueError):
            return [f"{label}: expected a number"]
        if not 0 <= number <= 100:
            errors.append(f"{label}: must be between 0 and 100")

    if field.get("maxlength") and isinstance(value, str) and len(value) > field["maxlength"]:
        errors.append(f"{label}: keep it under {field['maxlength']} characters")

    return errors


def _validate_selections(payload: dict, tax) -> list[str]:
    selections = payload.get("selections", {})
    errors: list[str] = []

    role_id = selections.get("role_id")
    if role_id not in tax.roles:
        return ["Pick a role before submitting"]

    service_ids = selections.get("service_ids") or []
    valid_services = {s["id"] for s in tax.services_of_role(role_id)}
    if not 1 <= len(service_ids) <= 3:
        errors.append("Choose between 1 and 3 business services")
    for service_id in service_ids:
        if service_id not in valid_services:
            errors.append(f"'{service_id}' isn't a business service of {tax.roles[role_id]['name']}")

    vc_ids = selections.get("vc_ids") or []
    if len(vc_ids) < 3:
        errors.append("Choose at least 3 value constructs")
    for vc_id in vc_ids:
        if tax.service_of_vc.get(vc_id) not in service_ids:
            errors.append(f"'{vc_id}' doesn't belong to the business services you chose")

    return errors


def _validate_ratings(payload: dict, tax) -> list[str]:
    ratings = payload.get("ratings", {})
    if not isinstance(ratings, dict):
        return ["Ratings must be an object of skill id to 1-5"]

    errors: list[str] = []
    for skill_id, value in ratings.items():
        if skill_id not in tax.skills:
            errors.append(f"Unknown skill '{skill_id}'")
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            errors.append(f"Rating for '{skill_id}' must be a number")
            continue
        if not 1 <= number <= 5:
            errors.append(f"Rating for '{skill_id}' must be between 1 and 5")

    selections = payload.get("selections", {})
    expected = tax.skills_of_vcs(selections.get("vc_ids") or [])
    missing = [s for s in expected if s not in ratings]
    if missing:
        errors.append(f"{len(missing)} skill(s) from the work you chose are still unrated")

    return errors[:20]


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False
