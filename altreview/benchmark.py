"""Offline rendering of pinned W3C ACT 23a2a8 fixtures, with source assets and isolated labels."""

import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from . import storage
from .capture import collect
from .facts import ENGINE_VERSION

FIXTURES = Path(__file__).resolve().parents[1] / "evaluation" / "act"
HIDDEN_REASONS = {"ariaHiddenElement", "ariaHiddenSubtree", "notRendered", "notVisible", "inertElement", "inertSubtree"}


def outcome(images):
    applicable = []
    for row in images:
        ax = row.get("image_ax", {})
        if not ax.get("available"):
            applicable.append("unknown")
        elif row.get("aria_hidden") or (ax.get("ignored") and HIDDEN_REASONS.intersection(ax.get("ignored_reasons", []))):
            continue
        elif ax.get("ignored") or ax.get("role") in {"none", "presentation"}:
            applicable.append("passed")
        elif ax.get("role") in {"image", "img"}:
            applicable.append("passed" if (ax.get("name") or "").strip() else "failed")
        else:
            continue
    if "failed" in applicable:
        return "failed"
    if "unknown" in applicable:
        return "unknown"
    return "passed" if applicable else "inapplicable"


def metrics(predictions, references):
    if set(predictions) != set(references):
        raise ValueError("Prediction and reference IDs must match exactly; no silent case dropping.")
    total = len(references)
    matched = sum(predictions[key] == label for key, label in references.items())
    unknown = sum(value == "unknown" for value in predictions.values())
    return {"cases": total, "matched": matched, "unknown": unknown,
        "agreement": matched / total if total else None, "reference_counts": dict(Counter(references.values()))}


def evaluate(destination=None):
    from playwright.sync_api import sync_playwright
    manifest = json.loads((FIXTURES / "inputs.json").read_text(encoding="utf-8"))
    assets = {}
    for item in manifest["assets"]:
        data = base64.b64decode((FIXTURES / item["file"]).read_bytes())
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("A pinned fixture asset has changed.")
        assets[item["url"]] = data
    predictions = {}
    details = []
    with TemporaryDirectory() as tmp, patch.object(storage, "RUNS", Path(tmp)), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("ALTREVIEW_BROWSER"))
        version = browser.version
        try:
            for item in manifest["cases"]:
                html = (FIXTURES / "inputs" / f'{item["id"]}.html').read_bytes()
                if hashlib.sha256(html).hexdigest() != item["sha256"]:
                    raise ValueError(f'Fixture changed: {item["id"]}')
                context = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block")
                def route(request):
                    if request.request.url == item["url"]:
                        request.fulfill(body=html, content_type="text/html")
                    elif request.request.url in assets:
                        request.fulfill(body=assets[request.request.url], content_type="image/png")
                    else:
                        request.abort()
                context.route("**/*", route)
                page = context.new_page()
                run = storage.new_run(item["url"], 0)
                try:
                    page.goto(item["url"], wait_until="load")
                    collect(page, run, capture_limit=0)
                    decision = outcome(run["images"])
                    details.append({"id": item["id"], "decision": decision, "nodes": [
                        {"tag": r["tag"], "image_ax": r["image_ax"]} for r in run["images"]]})
                except Exception as error:
                    decision = "unknown"
                    details.append({"id": item["id"], "decision": decision, "error": str(error)[:200]})
                predictions[item["id"]] = decision
                context.close()
        finally:
            browser.close()
    # Labels are read only after all browser predictions are complete.
    references_data = (FIXTURES / "references.json").read_bytes()
    references = {row["id"]: row["expected"] for row in json.loads(references_data)}
    for row in details:
        row["reference"] = references[row["id"]]
    report = {"scope": "Agreement with W3C ACT 23a2a8 only; not visual quality or full WCAG conformance.",
        "engine": ENGINE_VERSION, "browser": version, "at": datetime.now(timezone.utc).isoformat(),
        "rendering": "Unaltered pinned HTML and source image assets served offline at their original URLs; all other requests blocked.",
        "manifest_sha256": hashlib.sha256((FIXTURES/'inputs.json').read_bytes()).hexdigest(),
        "references_sha256": hashlib.sha256(references_data).hexdigest(),
        **metrics(predictions, references), "details": details}
    if destination:
        storage.write_json(destination, report)
    return report
