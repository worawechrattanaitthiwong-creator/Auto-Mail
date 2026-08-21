from __future__ import annotations

import os
import re
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path


class OutputBundleError(RuntimeError):
    pass


OUTPUT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("transfer_scx_ffm_in", "Dynamics SCX_FFM IN "),
    ("transfer_scx_ffm_out", "Dynamics SCX_FFM Out "),
    ("transfer_zz_cnn_in", "Dynamics ZZ_CNN IN "),
    ("purchase_prt_zz_cnn", "PRT.ZZ_CNN "),
    ("purchase_rc_scx_ffm", "Rc.SCX_FFM "),
    ("purchase_rc_scx_wh1", "Rc.SCX_WH1 "),
    ("purchase_rc_scx_xd", "Rc.SCX_XD "),
    ("transfer_status_created", "Tranfer order lines Status Created "),
    ("transfer_status_deleted", "Tranfer order lines Status Deleted "),
    ("transfer_status_received", "Tranfer order lines Status Received "),
    ("transfer_status_shipped", "Tranfer order lines Status Shipped "),
    ("transfer_order_diff", "TransferOrderDiff_ "),
)

DATE_RE = re.compile(r"(\d{2}-\d{2}-\d{4})")


def classify_output_filename(filename: str) -> tuple[str, date]:
    name = Path(filename).name
    if not name.lower().endswith(".xlsx"):
        raise OutputBundleError(f"ไม่ใช่ไฟล์ .xlsx: {name}")

    key = next((key for key, prefix in OUTPUT_PREFIXES if name.startswith(prefix)), None)
    if key is None:
        raise OutputBundleError(f"ไม่รู้จักไฟล์ผลลัพธ์: {name}")

    match = DATE_RE.search(name)
    if not match:
        raise OutputBundleError(f"หา日期ในชื่อไฟล์ไม่พบ: {name}")
    try:
        report_date = datetime.strptime(match.group(1), "%d-%m-%Y").date()
    except ValueError as exc:
        raise OutputBundleError(f"วันที่ในชื่อไฟล์ไม่ถูกต้อง: {name}") from exc
    return key, report_date


def map_output_files(paths: list[Path]) -> tuple[dict[str, Path], date]:
    expected_keys = {key for key, _ in OUTPUT_PREFIXES}
    outputs: dict[str, Path] = {}
    dates: set[date] = set()

    for path in paths:
        key, report_date = classify_output_filename(path.name)
        if key in outputs:
            raise OutputBundleError(f"พบไฟล์ผลลัพธ์ชนิด {key} ซ้ำ")
        outputs[key] = path
        dates.add(report_date)

    missing = expected_keys - set(outputs)
    extra_count = len(paths) - len(outputs)
    if missing or extra_count:
        details = []
        if missing:
            details.append("ขาด " + ", ".join(sorted(missing)))
        if extra_count:
            details.append(f"มีไฟล์ที่ไม่ตรงชุด {extra_count} ไฟล์")
        raise OutputBundleError("ZIP ผลลัพธ์ไม่ครบ 12 ไฟล์: " + "; ".join(details))
    if len(outputs) != len(expected_keys):
        raise OutputBundleError(f"ต้องมีไฟล์ผลลัพธ์ 12 ไฟล์ แต่พบ {len(outputs)} ไฟล์")
    if len(dates) != 1:
        raise OutputBundleError("วันที่ของไฟล์ผลลัพธ์ใน ZIP ไม่ตรงกัน")

    return outputs, dates.pop()


def extract_output_zip(zip_path: Path, output_dir: Path) -> tuple[dict[str, Path], date]:
    output_dir.mkdir(parents=True, exist_ok=True)
    max_uncompressed_mb = float(os.getenv("OUTPUT_ZIP_MAX_UNCOMPRESSED_MB", "500"))
    max_uncompressed_bytes = int(max_uncompressed_mb * 1024 * 1024)

    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise OutputBundleError("ไฟล์ ZIP เปิดไม่ได้หรือเสียหาย") from exc

    extracted: list[Path] = []
    with archive:
        xlsx_infos = [info for info in archive.infolist() if not info.is_dir() and info.filename.lower().endswith(".xlsx")]
        if len(xlsx_infos) != 12:
            raise OutputBundleError(f"ZIP ต้องมีไฟล์ .xlsx 12 ไฟล์ แต่พบ {len(xlsx_infos)} ไฟล์")
        total_uncompressed = sum(info.file_size for info in xlsx_infos)
        if total_uncompressed > max_uncompressed_bytes:
            raise OutputBundleError(
                f"ZIP เมื่อแตกไฟล์ใหญ่เกิน {max_uncompressed_mb:g} MB กรุณาใช้ชุดผลลัพธ์ที่เล็กลง"
            )

        seen_names: set[str] = set()
        for info in xlsx_infos:
            basename = Path(info.filename).name
            if not basename or basename in seen_names:
                raise OutputBundleError(f"ชื่อไฟล์ใน ZIP ซ้ำหรือไม่ถูกต้อง: {basename or info.filename}")
            seen_names.add(basename)
            target = output_dir / basename
            with archive.open(info) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=4 * 1024 * 1024)
            extracted.append(target)

    try:
        return map_output_files(extracted)
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
