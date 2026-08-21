from __future__ import annotations

import json
import mimetypes
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from .drive import DriveError, GoogleDriveUploader


class MailError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    use_tls: bool
    use_ssl: bool

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        required = {
            "SMTP_HOST": os.getenv("SMTP_HOST", "").strip(),
            "SMTP_USERNAME": os.getenv("SMTP_USERNAME", "").strip(),
            "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", ""),
            "SMTP_FROM": os.getenv("SMTP_FROM", "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise MailError("ตั้งค่า SMTP ยังไม่ครบ: " + ", ".join(missing))
        return cls(
            host=required["SMTP_HOST"],
            port=int(os.getenv("SMTP_PORT", "587")),
            username=required["SMTP_USERNAME"],
            password=required["SMTP_PASSWORD"],
            from_address=required["SMTP_FROM"],
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"},
            use_ssl=os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes", "on"},
        )


def load_email_jobs(config_path: Path) -> list[dict]:
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise MailError("config/email_jobs.json ต้องเป็น JSON array")
    return data


def _attach_file(message: EmailMessage, path: Path) -> None:
    mime, _ = mimetypes.guess_type(path.name)
    maintype, subtype = (mime or "application/octet-stream").split("/", 1)
    with path.open("rb") as handle:
        message.add_attachment(handle.read(), maintype=maintype, subtype=subtype, filename=path.name)


def _looks_like_email(value: str) -> bool:
    value = value.strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def _estimated_encoded_mb(paths: list[Path]) -> float:
    raw_bytes = sum(path.stat().st_size for path in paths)
    return (raw_bytes * 4 / 3) / (1024 * 1024) + 0.15


def plan_delivery(
    attachment_keys: list[str],
    outputs: dict[str, Path],
    direct_attachment_max_mb: float,
) -> tuple[list[str], list[str]]:
    """Use either all direct attachments or all Drive links for one email."""
    attachment_keys = list(attachment_keys)
    paths = [outputs[key] for key in attachment_keys]
    if _estimated_encoded_mb(paths) <= direct_attachment_max_mb:
        return attachment_keys, []
    return [], attachment_keys


def _drive_fallback_enabled() -> bool:
    return os.getenv("DRIVE_FALLBACK_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def send_configured_emails(
    outputs: dict[str, Path],
    report_date: date,
    config_path: Path,
    progress: Callable[[int, str], None] | None = None,
    *,
    mode: str = "live",
    test_recipient: str | None = None,
    jobs_override: list[dict] | None = None,
) -> list[dict]:
    if os.getenv("EMAIL_SEND_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise MailError("EMAIL_SEND_ENABLED=false จึงยังไม่อนุญาตให้ส่งอีเมล")

    if mode not in {"live", "test"}:
        raise MailError("โหมดส่งอีเมลไม่ถูกต้อง")
    if mode == "test":
        test_recipient = (test_recipient or "").strip()
        if not _looks_like_email(test_recipient):
            raise MailError("กรุณากรอกอีเมลทดสอบให้ถูกต้อง")

    settings = SmtpSettings.from_env()
    source_jobs = jobs_override if jobs_override is not None else load_email_jobs(config_path)
    jobs = [job for job in source_jobs if job.get("enabled", False)]
    if not jobs:
        raise MailError("ยังไม่มี email job ที่ enabled=true")

    direct_attachment_max_mb = float(os.getenv("DIRECT_ATTACHMENT_MAX_MB", "20"))
    plans: dict[str, tuple[list[str], list[str]]] = {}
    needs_drive = False

    for job in jobs:
        if mode == "live" and not job.get("to"):
            raise MailError(f"Email job '{job.get('id', 'unknown')}' ยังไม่มีผู้รับ To")

        attachment_keys = list(job.get("attachments", []))
        missing = [key for key in attachment_keys if key not in outputs]
        if missing:
            raise MailError(f"Email job '{job.get('id')}' หาไฟล์แนบไม่พบ: {', '.join(missing)}")

        direct_keys, link_keys = plan_delivery(attachment_keys, outputs, direct_attachment_max_mb)
        plans[str(job.get("id"))] = (direct_keys, link_keys)
        needs_drive = needs_drive or bool(link_keys)

    if needs_drive and not _drive_fallback_enabled():
        raise MailError(
            "มีอีเมลที่ไฟล์แนบรวมใหญ่เกิน DIRECT_ATTACHMENT_MAX_MB แต่ DRIVE_FALLBACK_ENABLED=false"
        )

    drive: GoogleDriveUploader | None = None
    drive_cache: dict[str, dict[str, str]] = {}
    if needs_drive:
        try:
            drive = GoogleDriveUploader.from_env()
        except DriveError as exc:
            raise MailError(str(exc)) from exc

    context = {
        "date": report_date.strftime("%d-%m-%Y"),
        "date_slash": report_date.strftime("%d/%m/%Y"),
        "time": "19.00",
    }
    results: list[dict] = []
    ssl_context = ssl.create_default_context()
    smtp = (
        smtplib.SMTP_SSL(settings.host, settings.port, timeout=60, context=ssl_context)
        if settings.use_ssl
        else smtplib.SMTP(settings.host, settings.port, timeout=60)
    )

    with smtp:
        if not settings.use_ssl and settings.use_tls:
            smtp.starttls(context=ssl_context)
        smtp.login(settings.username, settings.password)

        for index, job in enumerate(jobs, start=1):
            job_id = str(job.get("id"))
            direct_keys, link_keys = plans[job_id]
            intended_to = list(job.get("to", []))
            intended_cc = list(job.get("cc", []))
            actual_to = [test_recipient] if mode == "test" else intended_to
            actual_cc: list[str] = [] if mode == "test" else intended_cc

            drive_links: list[dict[str, str]] = []
            if link_keys:
                if drive is None:
                    raise MailError("Google Drive fallback ยังไม่พร้อมใช้งาน")
                for key in link_keys:
                    cache_key = str(outputs[key].resolve())
                    if cache_key not in drive_cache:
                        try:
                            drive_cache[cache_key] = drive.upload(outputs[key])
                        except DriveError as exc:
                            raise MailError(str(exc)) from exc
                    drive_links.append(drive_cache[cache_key])

            message = EmailMessage()
            message["From"] = settings.from_address
            message["To"] = ", ".join(actual_to)
            if actual_cc:
                message["Cc"] = ", ".join(actual_cc)

            subject = str(job.get("subject", "")).format(**context)
            if mode == "test":
                subject = f"[TEST] {subject}"
            message["Subject"] = subject

            body = str(job.get("body", "")).format(**context)
            if drive_links:
                lines = [
                    "",
                    "ไฟล์แนบรวมมีขนาดใหญ่ ระบบจึงส่งเป็นลิงก์ Google Drive แทนทั้งหมด:",
                    *[f"- {item['name']}: {item['url']}" for item in drive_links],
                ]
                body += "\n" + "\n".join(lines)
            message.set_content(body)

            for key in direct_keys:
                _attach_file(message, outputs[key])

            smtp.send_message(message)

            delivery = "drive_link" if link_keys else "attachment"
            result = {
                "id": job.get("id"),
                "name": job.get("name", job.get("id")),
                "mode": mode,
                "delivery": delivery,
                "to": actual_to,
                "cc": actual_cc,
                "intended_to": intended_to,
                "intended_cc": intended_cc,
                "subject": message["Subject"],
                "attachments": [outputs[key].name for key in direct_keys],
                "drive_links": drive_links,
                "all_files": [outputs[key].name for key in job.get("attachments", [])],
                "status": "sent",
            }
            results.append(result)
            if progress:
                pct = 87 + int(index / max(len(jobs), 1) * 13)
                label = "ทดสอบส่ง" if mode == "test" else "ส่งอีเมล"
                suffix = " (Drive link ทั้งชุด)" if link_keys else " (แนบไฟล์ทั้งหมด)"
                progress(min(pct, 100), f"{label} {index}/{len(jobs)} สำเร็จ{suffix}")

    return results
