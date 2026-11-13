"""Readable, localized messages for request-validation errors (HTTP 422).

FastAPI/pydantic report invalid parameters as a list of English, machine-oriented dicts. The UI
shows ``detail`` to the user, so it is turned into one sentence in the request's language; the
original list stays available under ``errors`` for scripts.
"""
from __future__ import annotations

from typing import Any

_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "less_than": "must be less than {lt}",
        "less_than_equal": "must be at most {le}",
        "greater_than": "must be greater than {gt}",
        "greater_than_equal": "must be at least {ge}",
        "string_pattern_mismatch": "has an invalid value",
        "literal_error": "must be one of: {expected}",
        "missing": "is required",
        "float_parsing": "must be a number",
        "int_parsing": "must be a whole number",
        "string_too_long": "is too long (max {max_length} characters)",
        "string_too_short": "is too short",
        "_default": "is invalid",
        "_sentence": "Invalid parameter '{field}': {problem}.",
    },
    "az": {
        "less_than": "{lt}-dən kiçik olmalıdır",
        "less_than_equal": "ən çox {le} ola bilər",
        "greater_than": "{gt}-dən böyük olmalıdır",
        "greater_than_equal": "ən azı {ge} olmalıdır",
        "string_pattern_mismatch": "yanlış dəyərdir",
        "literal_error": "bunlardan biri olmalıdır: {expected}",
        "missing": "mütləqdir",
        "float_parsing": "rəqəm olmalıdır",
        "int_parsing": "tam ədəd olmalıdır",
        "string_too_long": "çox uzundur (ən çox {max_length} simvol)",
        "string_too_short": "çox qısadır",
        "_default": "yanlışdır",
        "_sentence": "Yanlış parametr '{field}': {problem}.",
    },
}


def localize_errors(errors: list[dict[str, Any]], locale: str = "en") -> str:
    t = _TEMPLATES.get((locale or "en").lower(), _TEMPLATES["en"])
    out = []
    for e in errors[:3]:
        loc = [str(x) for x in e.get("loc", ()) if x not in ("query", "body", "path")]
        field = ".".join(loc) or "?"
        ctx = {k: v for k, v in (e.get("ctx") or {}).items()}
        tmpl = t.get(str(e.get("type")), t["_default"])
        try:
            problem = tmpl.format(**ctx)
        except (KeyError, IndexError):
            problem = t["_default"]
        out.append(t["_sentence"].format(field=field, problem=problem))
    return " ".join(out) or t["_sentence"].format(field="?", problem=t["_default"])
