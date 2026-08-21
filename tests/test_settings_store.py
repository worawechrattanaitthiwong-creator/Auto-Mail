import json
from pathlib import Path

import pytest

from app.settings_store import SettingsError, apply_email_settings, load_email_settings, save_email_settings


def make_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "id": "job1",
                    "name": "1. Job One",
                    "enabled": True,
                    "to": [],
                    "cc": [],
                    "subject": "Hello {date_slash}",
                    "attachments": ["a"],
                },
                {
                    "id": "job2",
                    "name": "2. Job Two",
                    "enabled": True,
                    "to": [],
                    "cc": [],
                    "subject": "World",
                    "attachments": ["b"],
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_save_and_reload_email_settings(tmp_path: Path) -> None:
    config = make_config(tmp_path / "email_jobs.json")
    settings_path = tmp_path / "email_settings.json"

    saved = save_email_settings(
        settings_path,
        config,
        {
            "test_email": "tester@example.com",
            "jobs": [
                {"id": "job1", "to": "a@example.com; b@example.com", "cc": "boss@example.com"},
                {"id": "job2", "to": "c@example.com\nd@example.com", "cc": ""},
            ],
        },
    )

    assert saved["test_email"] == "tester@example.com"
    assert saved["jobs"][0]["to"] == ["a@example.com", "b@example.com"]
    assert saved["jobs"][1]["to"] == ["c@example.com", "d@example.com"]

    reloaded = load_email_settings(settings_path, config)
    assert reloaded == saved


def test_apply_settings_overrides_only_recipients(tmp_path: Path) -> None:
    config = make_config(tmp_path / "email_jobs.json")
    templates = json.loads(config.read_text(encoding="utf-8"))
    settings = {
        "test_email": "tester@example.com",
        "jobs": [
            {
                "id": "job1",
                "name": "1. Job One",
                "enabled": True,
                "to": ["a@example.com"],
                "cc": ["cc@example.com"],
                "subject": "ignored",
                "attachments": [],
            }
        ],
    }

    merged = apply_email_settings(templates, settings)
    assert merged[0]["to"] == ["a@example.com"]
    assert merged[0]["cc"] == ["cc@example.com"]
    assert merged[0]["subject"] == "Hello {date_slash}"
    assert merged[0]["attachments"] == ["a"]


def test_invalid_email_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path / "email_jobs.json")
    with pytest.raises(SettingsError):
        save_email_settings(
            tmp_path / "email_settings.json",
            config,
            {"test_email": "bad-address", "jobs": []},
        )
