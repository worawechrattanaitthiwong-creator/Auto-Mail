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


def send_configured_emails(
    outputs: dict[str, Path],
    report_date: date,
    config_path: Path,
    progress: Callable[[int, str], None] | None = None,
) -> list[dict]:
    if os.getenv("EMAIL_SEND_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise MailError("EMAIL_SEND_ENABLED=false จึงยังไม่อนุญาตให้ส่งอีเมลจริง")

    settings = SmtpSettings.from_env()
    jobs = [job for job in load_email_jobs(config_path) if job.get("enabled", False)]
    if not jobs:
        raise MailError("ยังไม่มี email job ที่ enabled=true ใน config/email_jobs.json")

    for job in jobs:
        if not job.get("to"):
            raise MailError(f"Email job '{job.get('id', 'unknown')}' ยังไม่มีผู้รับ To")
        missing = [key for key in job.get("attachments", []) if key not in outputs]
        if missing:
            raise MailError(f"Email job '{job.get('id')}' หาไฟล์แนบไม่พบ: {', '.join(missing)}")

    context = {
        "date": report_date.strftime("%d-%m-%Y"),
        "time": "09.00",
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
            message = EmailMessage()
            message["From"] = settings.from_address
            message["To"] = ", ".join(job.get("to", []))
            if job.get("cc"):
                message["Cc"] = ", ".join(job["cc"])
            message["Subject"] = str(job.get("subject", "")).format(**context)
            message.set_content(str(job.get("body", "")).format(**context))
            for key in job.get("attachments", []):
                _attach_file(message, outputs[key])

            smtp.send_message(message)
            result = {
                "id": job.get("id"),
                "to": job.get("to", []),
                "cc": job.get("cc", []),
                "subject": message["Subject"],
                "attachments": [outputs[key].name for key in job.get("attachments", [])],
                "status": "sent",
            }
            results.append(result)
            if progress:
                pct = 87 + int(index / max(len(jobs), 1) * 13)
                progress(min(pct, 100), f"ส่งอีเมล {index}/{len(jobs)} สำเร็จ")

    return results
