"""Atomic scan checkpoints and observation caches, separate from the old prototype."""

from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "v2"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def new_run(url, limit):
    identifier = uuid.uuid4().hex
    return {"schema_version": 2, "id": identifier, "requested_url": url, "url": url,
            "title": url, "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "capturing", "capture_limit": limit, "discovered": 0, "images": [], "warnings": []}


def run_directory(run):
    identifier = run.get("id", "")
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid scan identifier.")
    return RUNS / identifier


def save(run):
    write_json(run_directory(run) / "scan.json", run)


def image_path(run, record):
    name = record.get("capture_file")
    if not name or Path(name).name != name:
        raise ValueError("This image has no local capture.")
    return run_directory(run) / name


def load(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != 2:
        raise ValueError("Open a version-two scan. Prototype reports are available on the archived branch.")
    run_directory(value)
    return value


def history():
    return sorted(RUNS.glob("*/scan.json"), key=lambda path: path.stat().st_mtime, reverse=True)
