from __future__ import annotations

import os
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .mailer import MailError, load_email_jobs, send_configured_emails
from .processor import ProcessingError, process_all, validate_upload_set

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "runs"
CONFIG_PATH = BASE_DIR / "config" / "email_jobs.json"
STATIC_DIR = BASE_DIR / "app" / "static"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Auto Mail", version="0.1.0")
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
    send_email: bool = True


RUNS: dict[str, RunState] = {}
RUN_LOCK = threading.Lock()


def require_access_key(x_app_key: str | None) -> None:
    expected = os.getenv("APP_ACCESS_KEY", "").strip()
    if expected and x_app_key != expected:
        raise HTTPException(status_code=401, detail="Access key ไม่ถูกต้อง")


def update_run(run_id: str, **changes: Any) -> None:
    with RUN_LOCK:
        state = RUNS[run_id]
        for key, value in changes.items():
            setattr(state, key, value)


def run_pipeline(run_id: str, input_paths: dict[str, Path], report_date: date, send_email: bool) -> None:
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
        if send_email:
            update_run(run_id, status="sending", message="กำลังส่งอีเมล")
            emails = send_configured_emails(outputs, report_date, CONFIG_PATH, progress)

        update_run(
            run_id,
            status="completed",
            progress=100,
            message="ประมวลผลและส่งอีเมลเรียบร้อย" if send_email else "ประมวลผลไฟล์เรียบร้อย (ไม่ได้ส่งอีเมล)",
            emails=emails,
        )
    except (ProcessingError, MailError, Exception) as exc:
        update_run(run_id, status="failed", error=str(exc), message="งานไม่สำเร็จ")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config-status")
def config_status(_: None = Header(default=None, alias="X-Ignored")) -> dict[str, Any]:
    jobs = load_email_jobs(CONFIG_PATH)
    enabled = [job for job in jobs if job.get("enabled", False)]
    return {
        "email_send_enabled": os.getenv("EMAIL_SEND_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        "smtp_configured": all(os.getenv(key) for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")),
        "jobs_total": len(jobs),
        "jobs_enabled": len(enabled),
        "jobs_with_recipients": sum(1 for job in enabled if job.get("to")),
        "access_key_required": bool(os.getenv("APP_ACCESS_KEY", "").strip()),
    }


@app.post("/api/runs")
async def create_run(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    send_email: bool = Form(True),
    x_app_key: str | None = Header(default=None),
) -> JSONResponse:
    require_access_key(x_app_key)
    if len(files) != 3:
        raise HTTPException(status_code=400, detail="กรุณาแนบไฟล์ 3 ไฟล์พอดี")

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
        send_email=send_email,
        message="อัปโหลดไฟล์ครบแล้ว",
    )
    with RUN_LOCK:
        RUNS[run_id] = state

    background_tasks.add_task(run_pipeline, run_id, input_paths, report_date, send_email)
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
