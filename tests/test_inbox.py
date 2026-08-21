from email.message import EmailMessage
from pathlib import Path

from app.inbox import GmailInboxWatcher, InboxSettings


def make_settings(allowed_senders: tuple[str, ...] = ()) -> InboxSettings:
    return InboxSettings(
        host="imap.gmail.com",
        port=993,
        username="central@example.com",
        password="secret",
        folder="INBOX",
        poll_seconds=60,
        scan_limit=200,
        max_report_age_days=3,
        allowed_senders=allowed_senders,
    )


def make_message(sender: str, filename: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "central@example.com"
    msg["Subject"] = "Report"
    msg.set_content("attached")
    msg.add_attachment(
        b"xlsx-bytes",
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
    return msg


def test_saves_matching_report_attachment(tmp_path: Path) -> None:
    watcher = GmailInboxWatcher(make_settings(), tmp_path / "inbox", tmp_path / "state.json")
    state = {"seen_uids": [], "files": {}, "launched_dates": []}
    watcher._save_matching_attachments(
        make_message("sender@example.com", "TransferOrder_2026082019.xlsx"),
        "10",
        state,
    )
    saved = state["files"]["2026-08-20"]["transfer_order"]
    assert Path(saved["path"]).exists()
    assert saved["filename"] == "TransferOrder_2026082019.xlsx"


def test_rejects_sender_not_in_allowlist(tmp_path: Path) -> None:
    watcher = GmailInboxWatcher(
        make_settings(("allowed@example.com",)),
        tmp_path / "inbox",
        tmp_path / "state.json",
    )
    state = {"seen_uids": [], "files": {}, "launched_dates": []}
    watcher._save_matching_attachments(
        make_message("other@example.com", "PurchaseOrder_2026082019.xlsx"),
        "11",
        state,
    )
    assert state["files"] == {}
