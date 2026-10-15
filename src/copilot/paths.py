"""Где что лежит. Всё, что относится к звонку, — в папке recordings/live/<дата_время>/."""
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "recordings/live"
PACKAGE = Path(__file__).resolve().parent


def new_call_folder():
    """recordings/live/<дата_время>/ и ссылка recordings/live/latest на неё."""
    LIVE.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    folder, n = LIVE / stamp, 1
    while folder.exists():
        n += 1
        folder = LIVE / f"{stamp}-{n}"
    folder.mkdir()
    latest = LIVE / "latest"
    latest.unlink(missing_ok=True)
    latest.symlink_to(folder.name)
    return folder
