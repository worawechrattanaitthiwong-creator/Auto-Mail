from __future__ import annotations

import email
import imaplib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path

from .processor import ProcessingError, classify_filename


class InboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class InboxSettings:
    host: str
    port: int
    username: str
    password: str
    folder: str
    poll_seconds: int
    scan_limit: int
    max_report_age_days: int
    allowed_senders: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "InboxSettings":
        username = os.getenv("INBOX_USERNAME", os.getenv("SMTP_USERNAME", "")).strip()
        password = os.getenv("INBOX_PASSWORD", os.getenv("SMTP_PASSWORD", ""))
        if not username or not password:
            raise InboxError("ตั้งค่า INBOX_USERNAME / INBOX_PASSWORD ยังไม่ครบ")
        allowed = tuple(
            item.strip().lower()
            for item in os.getenv("INBOX_ALLOWED_SENDERS", "").split(",")
            if item.strip()
        )
        return cls(
            host=os.getenv("INBOX_HOST", "imap.gmail.com").strip(),
            port=int(os.getenv("INBOX_PORT", "993")),
            username=username,
            password=password,
            folder=os.getenv("INBOX_FOLDER", "INBOX").strip() or "INBOX",
            poll_seconds=max(30, int(os.getenv("INBOX_POLL_SECONDS", "60"))),
            scan_limit=max(20, int(os.getenv("INBOX_SCAN_LIMIT", "200"))),
            max_report_age_days=max(0, int(os.getenv("INBOX_MAX_REPORT_AGE_DAYS", "3"))),
            allowed_senders=allowed,
        )


@dataclass(frozen=True)
class ReadyBatch:
    report_date: date
    paths: dict[str, Path]


def _decode_filename(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


class GmailInboxWatcher:
    def __init__(self, settings: InboxSettings, inbox_dir: Path, state_path: Path) -> None:
        self.settings = settings
        self.inbox_dir = inbox_dir
        self.state_path = state_path
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"seen_uids": [], "files": {}, "launched_dates": []}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.setdefault("seen_uids", [])
        data.setdefault("files", {})
        data.setdefault("launched_dates", [])
        return data

    def _save_state(self, state: dict) -> None:
        state["seen_uids"] = list(state.get("seen_uids", []))[-5000:]
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def mark_launched(self, report_date: date) -> None:
        state = self._load_state()
        key = report_date.isoformat()
        launched = set(state.get("launched_dates", []))
        launched.add(key)
        state["launched_dates"] = sorted(launched)
        self._save_state(state)

    def _sender_allowed(self, message) -> bool:
        if not self.settings.allowed_senders:
            return True
        sender = parseaddr(message.get("From", ""))[1].lower().strip()
        return sender in self.settings.allowed_senders

    def _save_matching_attachments(self, message, uid: str, state: dict) -> None:
        if not self._sender_allowed(message):
            return

        today = date.today()
        min_date = today - timedelta(days=self.settings.max_report_age_days)
        max_date = today + timedelta(days=1)

        for part in message.walk():
            filename = _decode_filename(part.get_filename())
            if not filename:
                continue
            filename = Path(filename).name
            try:
                item = classify_filename(filename)
            except ProcessingError:
                continue
            if not (min_date <= item.report_date <= max_date):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            date_key = item.report_date.isoformat()
            target_dir = self.inbox_dir / date_key
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            target.write_bytes(payload)

            files = state.setdefault("files", {}).setdefault(date_key, {})
            files[item.kind] = {
                "uid": uid,
                "filename": filename,
                "path": str(target),
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            }

    def scan_once(self) -> list[ReadyBatch]:
        state = self._load_state()
        seen = set(str(uid) for uid in state.get("seen_uids", []))

        try:
            client = imaplib.IMAP4_SSL(self.settings.host, self.settings.port)
            client.login(self.settings.username, self.settings.password)
            status, _ = client.select(self.settings.folder, readonly=True)
            if status != "OK":
                raise InboxError(f"เปิดโฟลเดอร์ {self.settings.folder} ไม่สำเร็จ")
            status, data = client.uid("search", None, "ALL")
            if status != "OK":
                raise InboxError("ค้นหาเมลใน Inbox ไม่สำเร็จ")

            all_uids = (data[0] or b"").split()
            for uid_bytes in all_uids[-self.settings.scan_limit :]:
                uid = uid_bytes.decode("ascii", errors="ignore")
                if uid in seen:
                    continue
                status, fetched = client.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK" or not fetched:
                    continue
                raw = next((item[1] for item in fetched if isinstance(item, tuple) and len(item) > 1), None)
                if raw:
                    message = email.message_from_bytes(raw)
                    self._save_matching_attachments(message, uid, state)
                seen.add(uid)
            try:
                client.logout()
            except Exception:
                pass
        except imaplib.IMAP4.error as exc:
            raise InboxError(f"เชื่อม Gmail Inbox ไม่สำเร็จ: {exc}") from exc

        state["seen_uids"] = sorted(seen, key=lambda value: int(value) if value.isdigit() else 0)
        self._save_state(state)

        launched = set(state.get("launched_dates", []))
        ready: list[ReadyBatch] = []
        required = {"transfer_order", "purchase_order", "transfer_order_diff"}
        for date_key, file_map in sorted(state.get("files", {}).items()):
            if date_key in launched or not required.issubset(file_map):
                continue
            paths = {kind: Path(file_map[kind]["path"]) for kind in required}
            if all(path.exists() for path in paths.values()):
                ready.append(ReadyBatch(report_date=date.fromisoformat(date_key), paths=paths))
        return ready
