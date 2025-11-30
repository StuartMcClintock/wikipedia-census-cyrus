import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "edit.log"


def log_edit_article(title: str, response: Dict[str, Any]) -> None:
    """
    Append a log entry for an edit attempt with timestamp and article title.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "article": title,
            "result": response or {},
        }
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        # Logging should never break the caller.
        pass
