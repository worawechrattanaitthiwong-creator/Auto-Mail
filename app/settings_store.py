from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


class SettingsError(RuntimeError):
    pass


_EMAIL_SPLIT = re.compile(r"[;,\n\r]+")
_DB_SETTING_KEY = "email_settings"


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


def settings_storage_backend() -> str:
    return "postgres" if os.getenv("DATABASE_URL", "").strip() else "file"


def _load_templates(config_path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SettingsError("อ่าน config/email_jobs.json ไม่สำเร็จ") from exc
    if not isinstance(data, list):
        raise SettingsError("config/email_jobs.json ต้องเป็น JSON array")
    return data


def _connect_database():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return None
    try:
        import psycopg

        return psycopg.connect(database_url, connect_timeout=10)
    except Exception as exc:
        raise SettingsError("เชื่อมฐานข้อมูลสำหรับ Email Settings ไม่สำเร็จ") from exc


def _ensure_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_mail_settings (
                setting_key TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    connection.commit()


def _load_stored_database() -> dict[str, Any]:
    connection = _connect_database()
    if connection is None:
        return {}
    try:
        _ensure_table(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM auto_mail_settings WHERE setting_key = %s",
                (_DB_SETTING_KEY,),
            )
            row = cursor.fetchone()
        if not row:
            return {}
        data = row[0]
        if isinstance(data, str):
            data = json.loads(data)
        return data if isinstance(data, dict) else {}
    except SettingsError:
        raise
    except Exception as exc:
        raise SettingsError("อ่าน Email Settings จากฐานข้อมูลไม่สำเร็จ") from exc
    finally:
        connection.close()


def _save_stored_database(data: dict[str, Any]) -> None:
    connection = _connect_database()
    if connection is None:
        raise SettingsError("ยังไม่ได้ตั้งค่า DATABASE_URL")
    try:
        _ensure_table(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO auto_mail_settings (setting_key, payload, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (setting_key)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                (_DB_SETTING_KEY, json.dumps(data, ensure_ascii=False)),
            )
        connection.commit()
    except SettingsError:
        raise
    except Exception as exc:
        connection.rollback()
        raise SettingsError("บันทึก Email Settings ลงฐานข้อมูลไม่สำเร็จ") from exc
    finally:
        connection.close()


def _load_stored_file(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SettingsError("อ่าน email settings ที่บันทึกไว้ไม่สำเร็จ") from exc
    return data if isinstance(data, dict) else {}


def _save_stored_file(settings_path: Path, data: dict[str, Any]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings_path)


def _load_stored(settings_path: Path) -> dict[str, Any]:
    if settings_storage_backend() == "postgres":
        return _load_stored_database()
    return _load_stored_file(settings_path)


def _save_stored(settings_path: Path, data: dict[str, Any]) -> None:
    if settings_storage_backend() == "postgres":
        _save_stored_database(data)
    else:
        _save_stored_file(settings_path, data)


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
    _save_stored(settings_path, data)
    return load_email_settings(settings_path, config_path)
