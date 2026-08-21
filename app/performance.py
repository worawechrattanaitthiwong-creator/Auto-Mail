from __future__ import annotations

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

_INSTALLED = False
_ORIGINAL_SAVE = Workbook.save


def _compression_level() -> int:
    raw = os.getenv("XLSX_COMPRESSION_LEVEL", "1").strip()
    try:
        return max(0, min(9, int(raw)))
    except ValueError:
        return 1


def install_fast_xlsx_save() -> None:
    """Use a low ZIP compression level for large generated XLSX files.

    XLSX is a ZIP container. The default zlib compression spends substantial CPU
    time on large report outputs. A low compression level trades somewhat larger
    files for much faster saves, which is preferable on the 0.1 CPU free worker.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    def fast_save(self: Workbook, filename: str | Path) -> None:
        if self.write_only and not self.worksheets:
            self.create_sheet()
        archive = ZipFile(
            filename,
            "w",
            ZIP_DEFLATED,
            allowZip64=True,
            compresslevel=_compression_level(),
        )
        writer = ExcelWriter(self, archive)
        writer.save()

    Workbook.save = fast_save
    _INSTALLED = True


def restore_default_xlsx_save() -> None:
    global _INSTALLED
    Workbook.save = _ORIGINAL_SAVE
    _INSTALLED = False
