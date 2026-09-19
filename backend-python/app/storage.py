import os
from pathlib import Path

from .database import RUNTIME_DATA_DIR


UPLOADS_ROOT = Path(os.getenv("UPLOADS_DIR", str(RUNTIME_DATA_DIR / "uploads"))).resolve()
BACKUPS_ROOT = Path(os.getenv("BACKUPS_DIR", str(RUNTIME_DATA_DIR / "backups"))).resolve()


def upload_path(*parts: str) -> Path:
    path = UPLOADS_ROOT.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_path() -> Path:
    BACKUPS_ROOT.mkdir(parents=True, exist_ok=True)
    return BACKUPS_ROOT
