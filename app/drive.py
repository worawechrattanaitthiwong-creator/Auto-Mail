from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


class DriveError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleDriveSettings:
    client_id: str
    client_secret: str
    refresh_token: str
    folder_id: str | None
    share_mode: str

    @classmethod
    def from_env(cls) -> "GoogleDriveSettings":
        required = {
            "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
            "GOOGLE_REFRESH_TOKEN": os.getenv("GOOGLE_REFRESH_TOKEN", "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise DriveError("ตั้งค่า Google Drive ยังไม่ครบ: " + ", ".join(missing))

        share_mode = os.getenv("GOOGLE_DRIVE_SHARE_MODE", "anyone_with_link").strip().lower()
        if share_mode != "anyone_with_link":
            raise DriveError("ตอนนี้ GOOGLE_DRIVE_SHARE_MODE รองรับเฉพาะ anyone_with_link")

        return cls(
            client_id=required["GOOGLE_CLIENT_ID"],
            client_secret=required["GOOGLE_CLIENT_SECRET"],
            refresh_token=required["GOOGLE_REFRESH_TOKEN"],
            folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip() or None,
            share_mode=share_mode,
        )


class GoogleDriveUploader:
    def __init__(self, settings: GoogleDriveSettings) -> None:
        credentials = Credentials(
            token=None,
            refresh_token=settings.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        self.settings = settings
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    @classmethod
    def from_env(cls) -> "GoogleDriveUploader":
        return cls(GoogleDriveSettings.from_env())

    def upload(self, path: Path) -> dict[str, str]:
        mime_type, _ = mimetypes.guess_type(path.name)
        metadata: dict[str, object] = {"name": path.name}
        if self.settings.folder_id:
            metadata["parents"] = [self.settings.folder_id]

        media = MediaFileUpload(
            str(path),
            mimetype=mime_type or "application/octet-stream",
            resumable=True,
        )
        created = (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,name,webViewLink,webContentLink",
            )
            .execute()
        )

        file_id = created.get("id")
        if not file_id:
            raise DriveError(f"Google Drive ไม่คืน file id สำหรับ {path.name}")

        if self.settings.share_mode == "anyone_with_link":
            self.service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ).execute()

        url = created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        return {
            "id": str(file_id),
            "name": path.name,
            "url": str(url),
        }
