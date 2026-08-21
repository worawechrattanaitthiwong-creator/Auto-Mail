from __future__ import annotations

import os

from .performance import install_fast_xlsx_save

# Shared-office mode: everyone with the web URL can use the app without entering
# the browser Access Key. Set ACCESS_CONTROL_ENABLED=true later if protection is
# needed again; APP_ACCESS_KEY can remain stored in Render without being exposed.
if os.getenv("ACCESS_CONTROL_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
    os.environ["APP_ACCESS_KEY"] = ""

install_fast_xlsx_save()

from .main import app  # noqa: E402,F401
