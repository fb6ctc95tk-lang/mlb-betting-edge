import re
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "ingestion.log"
_END_LINE = re.compile(r"\[(.+?)\] === INGESTION END exit=(\d+) ===")


@router.get("/ingestion")
def ingestion_health():
    if not LOG_PATH.exists():
        return {"last_run_at": None, "last_exit_code": None, "status": "unknown"}

    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()

    for line in reversed(lines):
        m = _END_LINE.search(line)
        if m:
            exit_code = int(m.group(2))
            return {
                "last_run_at": m.group(1),
                "last_exit_code": exit_code,
                "status": "healthy" if exit_code == 0 else "failed",
            }

    return {"last_run_at": None, "last_exit_code": None, "status": "unknown"}
