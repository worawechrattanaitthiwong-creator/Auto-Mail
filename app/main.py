from __future__ import annotations

import os
import shutil
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .inbox import GmailInboxWatcher, InboxError, InboxSettings, ReadyBatch
from .mailer import MailError, load_email_jobs, send_configured_emails
from .processor import ProcessingError, process_all, validate_upload_set
from .settings_store import SettingsError, apply_email_settings, load_email_settings, save_email_settings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("AUTO_MAIL_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
DATA_DIR = DATA_ROOT / "runs"
INBOX_DIR = DATA_ROOT / "inbox"
INBOX_STATE_PATH = DATA_ROOT / "mailbox_state.json"
EMAIL_SETTINGS_PATH = DATA_ROOT / "email_settings.json"
CONFIG_PATH = BASE_DIR / "config" / "email_jobs.json"
STATIC_DIR = BASE_DIR / "app" / "static"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Auto Mail", version="0.5.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@dataclass
class RunState:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "รอเริ่มงาน"
    report_date: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    outputs: list[str] = field(default_factory=list)
    emails: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    send_mode: str = "none"
    test_email: str | None = None
    source: str = "manual"


RUNS: dict[str, RunState] = {}
RUN_LOCK = threading.Lock()
WATCHER_STOP = threading.Event()
WATCHER_THREAD: threading.Thread | None = None
INBOX_STATUS: dict[str, Any] = {
    "enabled": False,
    "configured": False,
    "status": "disabled",
    "last_scan": None,
    "last_error": None,
    "last_batch": None,
}


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def require_access_key(x_app_key: str | None) -> None:
    expected = os.getenv("APP_ACCESS_KEY", "").strip()
    if expected and x_app_key != expected:
        raise HTTPException(status_code=401, detail="Access key ไม่ถูกต้อง")


def update_run(run_id: str, **changes: Any) -> None:
    with RUN_LOCK:
        state = RUNS[run_id]
        for key, value in changes.items():
            setattr(state, key, value)


def _runtime_settings() -> dict[str, Any]:
    return load_email_settings(
        EMAIL_SETTINGS_PATH,
        CONFIG_PATH,
        default_test_email=os.getenv("TEST_EMAIL_DEFAULT", "").strip(),
    )


def _configured_jobs() -> list[dict[str, Any]]:
    templates = load_email_jobs(CONFIG_PATH)
    return apply_email_settings(templates, _runtime_settings())


def _email_config() -> dict[str, Any]:
    jobs = _configured_jobs()
    enabled_jobs = [job for job in jobs if job.get("enabled", False)]
    email_send_enabled = _enabled("EMAIL_SEND_ENABLED")
    smtp_configured = all(os.getenv(key) for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"))
    jobs_with_recipients = sum(1 for job in enabled_jobs if job.get("to"))
    live_ready = (
        email_send_enabled
        and smtp_configured
        and bool(enabled_jobs)
        and jobs_with_recipients == len(enabled_jobs)
    )
    return {
        "jobs": jobs,
        "enabled_jobs": enabled_jobs,
        "email_send_enabled": email_send_enabled,
        "smtp_configured": smtp_configured,
        "jobs_with_recipients": jobs_with_recipients,
        "live_ready": live_ready,
    }


def run_pipeline(
    run_id: str,
    input_paths: dict[str, Path],
    report_date: date,
    send_mode: str,
    test_email: str | None,
) -> None:
    run_dir = DATA_DIR / run_id
    output_dir = run_dir / "outputs"

    def progress(percent: int, message: str) -> None:
        update_run(run_id, progress=percent, message=message, status="processing")

    try:
        outputs = process_all(
            transfer_order=input_paths["transfer_order"],
            purchase_order=input_paths["purchase_order"],
            transfer_order_diff=input_paths["transfer_order_diff"],
            output_dir=output_dir,
            report_date=report_date,
            progress=progress,
        )
        update_run(run_id, outputs=sorted(path.name for path in outputs.values()))

        emails: list[dict[str, Any]] = []
        if send_mode in {"test", "live"}:
            update_run(
                run_id,
                status="sending",
                message="กำลังทดสอบส่งอีเมล" if send_mode == "test" else "กำลังส่งอีเมลจริง",
            )
            emails = send_configured_emails(
                outputs,
                report_date,
                CONFIG_PATH,
                progress,
                mode=send_mode,
                test_recipient=test_email,
                jobs_override=_configured_jobs(),
            )

        if send_mode == "test":
            final_message = f"ประมวลผลไฟล์และทดสอบส่ง {len(emails)} อีเมลไปที่ {test_email} เรียบร้อย"
        elif send_mode == "live":
            final_message = f"ประมวลผลและส่งอีเมลจริง {len(emails)} ฉบับเรียบร้อย"
        else:
            final_message = "ประมวลผลไฟล์เรียบร้อย (ไม่ได้ส่งอีเมล)"

        update_run(
            run_id,
            status="completed",
            progress=100,
            message=final_message,
            emails=emails,
        )
    except (ProcessingError, MailError, SettingsError, Exception) as exc:
        update_run(run_id, status="failed", error=str(exc), message="งานไม่สำเร็จ")


def _launch_inbox_batch(watcher: GmailInboxWatcher, batch: ReadyBatch) -> str:
    run_id = "mail-" + uuid.uuid4().hex[:10]
    input_dir = DATA_DIR / run_id / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    input_paths: dict[str, Path] = {}
    for kind, source in batch.paths.items():
        target = input_dir / source.name
        shutil.copy2(source, target)
        input_paths[kind] = target

    state = RunState(
        id=run_id,
        report_date=batch.report_date.strftime("%d-%m-%Y"),
        send_mode="live",
        message="Inbox พบรายงานครบ 3 ไฟล์แล้ว",
        source="gmail_inbox",
    )
    with RUN_LOCK:
        RUNS[run_id] = state

    watcher.mark_launched(batch.report_date)
    worker = threading.Thread(
        target=run_pipeline,
        args=(run_id, input_paths, batch.report_date, "live", None),
        daemon=True,
        name=f"auto-mail-run-{run_id}",
    )
    worker.start()
    return run_id


def _inbox_watch_loop() -> None:
    INBOX_STATUS.update(enabled=True, status="starting", last_error=None)
    try:
        settings = InboxSettings.from_env()
        watcher = GmailInboxWatcher(settings, INBOX_DIR, INBOX_STATE_PATH)
        INBOX_STATUS.update(configured=True, status="waiting")
    except InboxError as exc:
        INBOX_STATUS.update(configured=False, status="error", last_error=str(exc))
        return

    while not WATCHER_STOP.is_set():
        try:
            mail_config = _email_config()
            if not mail_config["live_ready"]:
                INBOX_STATUS.update(status="waiting_email_config", last_error=None)
            else:
                ready_batches = watcher.scan_once()
                INBOX_STATUS.update(
                    status="watching",
                    last_scan=datetime.now().isoformat(timespec="seconds"),
                    last_error=None,
                )
                for batch in ready_batches:
                    run_id = _launch_inbox_batch(watcher, batch)
                    INBOX_STATUS.update(
                        status="processing",
                        last_batch={"report_date": batch.report_date.isoformat(), "run_id": run_id},
                    )
        except Exception as exc:
            INBOX_STATUS.update(
                status="error",
                last_scan=datetime.now().isoformat(timespec="seconds"),
                last_error=str(exc),
            )
        WATCHER_STOP.wait(settings.poll_seconds)


@app.on_event("startup")
def start_inbox_watcher() -> None:
    global WATCHER_THREAD
    if not _enabled("INBOX_WATCH_ENABLED"):
        INBOX_STATUS.update(enabled=False, configured=False, status="disabled")
        return
    if WATCHER_THREAD and WATCHER_THREAD.is_alive():
        return
    WATCHER_STOP.clear()
    WATCHER_THREAD = threading.Thread(target=_inbox_watch_loop, daemon=True, name="gmail-inbox-watcher")
    WATCHER_THREAD.start()


@app.on_event("shutdown")
def stop_inbox_watcher() -> None:
    WATCHER_STOP.set()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config-status")
def config_status(_: None = Header(default=None, alias="X-Ignored")) -> dict[str, Any]:
    mail_config = _email_config()
    enabled_jobs = mail_config["enabled_jobs"]
    drive_fallback_enabled = _enabled("DRIVE_FALLBACK_ENABLED")
    drive_configured = all(
        os.getenv(key)
        for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    )
    inbox_enabled = _enabled("INBOX_WATCH_ENABLED")
    inbox_configured = bool(
        os.getenv("INBOX_USERNAME", os.getenv("SMTP_USERNAME", "")).strip()
        and os.getenv("INBOX_PASSWORD", os.getenv("SMTP_PASSWORD", ""))
    )
    settings = _runtime_settings()
    return {
        "email_send_enabled": mail_config["email_send_enabled"],
        "smtp_configured": mail_config["smtp_configured"],
        "jobs_total": len(mail_config["jobs"]),
        "jobs_enabled": len(enabled_jobs),
        "jobs_with_recipients": mail_config["jobs_with_recipients"],
        "test_ready": mail_config["email_send_enabled"] and mail_config["smtp_configured"] and bool(enabled_jobs),
        "test_email_saved": bool(settings.get("test_email")),
        "live_ready": mail_config["live_ready"],
        "drive_fallback_enabled": drive_fallback_enabled,
        "drive_configured": drive_configured,
        "direct_attachment_max_mb": float(os.getenv("DIRECT_ATTACHMENT_MAX_MB", "20")),
        "inbox_watch_enabled": inbox_enabled,
        "inbox_configured": inbox_configured,
        "inbox_status": dict(INBOX_STATUS),
        "access_key_required": bool(os.getenv("APP_ACCESS_KEY", "").strip()),
    }


@app.get("/api/email-settings")
def get_email_settings(x_app_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_access_key(x_app_key)
    try:
        return _runtime_settings()
    except SettingsError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/email-settings")
def put_email_settings(
    payload: dict[str, Any] = Body(...),
    x_app_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_access_key(x_app_key)
    try:
        return save_email_settings(EMAIL_SETTINGS_PATH, CONFIG_PATH, payload)
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runs")
async def create_run(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    send_mode: str = Form("none"),
    test_email: str | None = Form(None),
    x_app_key: str | None = Header(default=None),
) -> JSONResponse:
    require_access_key(x_app_key)
    if len(files) != 3:
        raise HTTPException(status_code=400, detail="กรุณาแนบไฟล์ 3 ไฟล์พอดี")
    if send_mode not in {"none", "test", "live"}:
        raise HTTPException(status_code=400, detail="send_mode ต้องเป็น none, test หรือ live")
    if send_mode == "test":
        saved_test_email = str(_runtime_settings().get("test_email", "")).strip()
        candidate = (test_email or saved_test_email).strip()
        if "@" not in candidate or "." not in candidate.rsplit("@", 1)[-1]:
            raise HTTPException(status_code=400, detail="กรุณาบันทึก Test Email ให้ถูกต้องก่อนทดสอบส่ง")
        test_email = candidate
    else:
        test_email = None

    try:
        classified, report_date = validate_upload_set([item.filename or "" for item in files])
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_by_kind: dict[str, UploadFile] = {}
    for upload in files:
        item = next(value for value in classified.values() if value.filename == upload.filename)
        upload_by_kind[item.kind] = upload

    run_id = uuid.uuid4().hex[:12]
    run_dir = DATA_DIR / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    input_paths: dict[str, Path] = {}
    for kind, upload in upload_by_kind.items():
        target = input_dir / Path(upload.filename or f"{kind}.xlsx").name
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                handle.write(chunk)
        await upload.close()
        input_paths[kind] = target

    state = RunState(
        id=run_id,
        report_date=report_date.strftime("%d-%m-%Y"),
        send_mode=send_mode,
        test_email=test_email,
        message="อัปโหลดไฟล์ครบแล้ว",
        source="manual",
    )
    with RUN_LOCK:
        RUNS[run_id] = state

    background_tasks.add_task(run_pipeline, run_id, input_paths, report_date, send_mode, test_email)
    return JSONResponse(asdict(state), status_code=202)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, x_app_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_access_key(x_app_key)
    with RUN_LOCK:
        state = RUNS.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="ไม่พบ run นี้")
        return asdict(state)


@app.get("/api/runs/{run_id}/download")
def download_outputs(run_id: str, x_app_key: str | None = Header(default=None)) -> FileResponse:
    require_access_key(x_app_key)
    run_dir = DATA_DIR / run_id
    output_dir = run_dir / "outputs"
    if not output_dir.exists() or not list(output_dir.glob("*.xlsx")):
        raise HTTPException(status_code=404, detail="ยังไม่มีไฟล์ผลลัพธ์")

    zip_path = run_dir / f"Auto-Mail-{run_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.glob("*.xlsx")):
            archive.write(path, arcname=path.name)
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")
