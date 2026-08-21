from pathlib import Path

from app.mailer import plan_delivery


def make_sized_file(path: Path, size_mb: float) -> Path:
    path.write_bytes(b"0" * int(size_mb * 1024 * 1024))
    return path


def test_small_files_stay_as_attachments(tmp_path: Path) -> None:
    outputs = {
        "a": make_sized_file(tmp_path / "a.xlsx", 2.5),
        "b": make_sized_file(tmp_path / "b.xlsx", 7.5),
    }
    direct, links = plan_delivery(["a", "b"], outputs, 20)
    assert direct == ["a", "b"]
    assert links == []


def test_large_file_moves_to_drive(tmp_path: Path) -> None:
    outputs = {"large": make_sized_file(tmp_path / "large.xlsx", 24.5)}
    direct, links = plan_delivery(["large"], outputs, 20)
    assert direct == []
    assert links == ["large"]


def test_large_email_moves_all_files_to_drive(tmp_path: Path) -> None:
    outputs = {
        "small": make_sized_file(tmp_path / "small.xlsx", 2),
        "medium": make_sized_file(tmp_path / "medium.xlsx", 8),
        "large": make_sized_file(tmp_path / "large.xlsx", 10),
    }
    direct, links = plan_delivery(["small", "medium", "large"], outputs, 20)
    assert direct == []
    assert links == ["small", "medium", "large"]
