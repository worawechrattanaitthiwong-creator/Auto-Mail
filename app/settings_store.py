from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SettingsError(RuntimeError):
    pass


_EMAIL_SPLIT = re.compile(r"[;,\n\r]+")


def looks_like_email(value: str) -> bool:
    value = value.strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def normalize_addresses(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = _EMAIL_SPLIT.split(value)
    elif isinstance(value, list):
        candidates = [str(item) for item in value]
    else:
        raise SettingsError("รูปแบบรายชื่ออีเมลไม่ถูกต้อง")

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        address = candidate.strip()
        if not address:
            continue
        if not looks_like_email(address):
            raise SettingsError(f"อีเมลไม่ถูกต้อง: {address}")
        key = address.lower()
        if key not in seen:
            seen.add(key)
            result.append(address)
    return result


def _load_templates(config_path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SettingsError("อ่าน config/email_jobs.json ไม่สำเร็จ") from exc
    if not isinstance(data, list):
        raise SettingsError("config/email_jobs.json ต้องเป็น JSON array")
    return data


def _load_stored(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SettingsError("อ่าน email settings ที่บันทึกไว้ไม่สำเร็จ") from exc
    return data if isinstance(data, dict) else {}


def load_email_settings(
    settings_path: Path,
    config_path: Path,
    *,
    default_test_email: str = "",
) -> dict[str, Any]:
    templates = _load_templates(config_path)
    stored = _load_stored(settings_path)
    stored_jobs = stored.get("jobs", {}) if isinstance(stored.get("jobs", {}), dict) else {}

    if "test_email" in stored:
        test_email = str(stored.get("test_email", "")).strip()
    else:
        test_email = default_test_email.strip()

    jobs: list[dict[str, Any]] = []
    for template in templates:
        job_id = str(template.get("id", ""))
        override = stored_jobs.get(job_id, {}) if isinstance(stored_jobs.get(job_id, {}), dict) else {}
        jobs.append(
            {
                "id": job_id,
                "name": str(template.get("name", job_id)),
                "enabled": bool(template.get("enabled", False)),
                "to": normalize_addresses(override.get("to", template.get("to", []))),
                "cc": normalize_addresses(override.get("cc", template.get("cc", []))),
                "subject": str(template.get("subject", "")),
                "attachments": list(template.get("attachments", [])),
            }
        )

    return {"test_email": test_email, "jobs": jobs}


def apply_email_settings(
    templates: list[dict[str, Any]],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    settings_by_id = {
        str(job.get("id")): job
        for job in settings.get("jobs", [])
        if isinstance(job, dict) and job.get("id")
    }
    merged: list[dict[str, Any]] = []
    for template in templates:
        job = dict(template)
        override = settings_by_id.get(str(job.get("id")), {})
        job["to"] = normalize_addresses(override.get("to", job.get("to", [])))
        job["cc"] = normalize_addresses(override.get("cc", job.get("cc", [])))
        merged.append(job)
    return merged


def save_email_settings(
    settings_path: Path,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    templates = _load_templates(config_path)
    valid_ids = {str(job.get("id", "")) for job in templates}

    test_email = str(payload.get("test_email", "")).strip()
    if test_email and not looks_like_email(test_email):
        raise SettingsError("Test Email ไม่ถูกต้อง")

    raw_jobs = payload.get("jobs", [])
    if not isinstance(raw_jobs, list):
        raise SettingsError("jobs ต้องเป็นรายการ")

    stored_jobs: dict[str, dict[str, list[str]]] = {}
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue
        job_id = str(raw.get("id", "")).strip()
        if not job_id or job_id not in valid_ids:
            raise SettingsError(f"ไม่รู้จัก email job: {job_id or '(ว่าง)'}")
        stored_jobs[job_id] = {
            "to": normalize_addresses(raw.get("to", [])),
            "cc": normalize_addresses(raw.get("cc", [])),
        }

    data = {"test_email": test_email, "jobs": stored_jobs}
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings_path)

    return load_email_settings(settings_path, config_path)
