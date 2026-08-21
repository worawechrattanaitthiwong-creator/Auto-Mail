from datetime import date
from pathlib import Path
import zipfile

import pytest

from app.output_bundle import OutputBundleError, extract_output_zip


OUTPUT_NAMES = [
    "Dynamics SCX_FFM IN 21-08-2026 19.00.xlsx",
    "Dynamics SCX_FFM Out 21-08-2026 19.00.xlsx",
    "Dynamics ZZ_CNN IN 21-08-2026 19.00.xlsx",
    "PRT.ZZ_CNN 21-08-2026 19.00.xlsx",
    "Rc.SCX_FFM 21-08-2026 19.00.xlsx",
    "Rc.SCX_WH1 21-08-2026 19.00.xlsx",
    "Rc.SCX_XD 21-08-2026 19.00.xlsx",
    "Tranfer order lines Status Created 21-08-2026 19.00.xlsx",
    "Tranfer order lines Status Deleted 21-08-2026 19.00.xlsx",
    "Tranfer order lines Status Received 21-08-2026 19.00.xlsx",
    "Tranfer order lines Status Shipped 21-08-2026 19.00.xlsx",
    "TransferOrderDiff_ 21-08-2026 Time 19.00.xlsx",
]


def make_zip(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b"dummy-xlsx")
    return path


def test_extract_valid_output_zip(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "outputs.zip", OUTPUT_NAMES)
    outputs, report_date = extract_output_zip(zip_path, tmp_path / "extracted")

    assert report_date == date(2026, 8, 21)
    assert len(outputs) == 12
    assert outputs["purchase_rc_scx_xd"].name == "Rc.SCX_XD 21-08-2026 19.00.xlsx"
    assert all(path.exists() for path in outputs.values())


def test_output_zip_requires_all_12_files(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "outputs.zip", OUTPUT_NAMES[:-1])
    with pytest.raises(OutputBundleError, match="12"):
        extract_output_zip(zip_path, tmp_path / "extracted")


def test_output_zip_rejects_mixed_dates(tmp_path: Path) -> None:
    names = list(OUTPUT_NAMES)
    names[0] = names[0].replace("21-08-2026", "20-08-2026")
    zip_path = make_zip(tmp_path / "outputs.zip", names)
    with pytest.raises(OutputBundleError, match="วันที่"):
        extract_output_zip(zip_path, tmp_path / "extracted")
