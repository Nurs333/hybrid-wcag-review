"""Atomic name checks. A name-check pass never means an image or page passes WCAG."""

from urllib.parse import unquote

ENGINE_VERSION = "chromium-names-v1"


def alt_kind(value):
    if value is None:
        return "missing"
    normalized = value.strip().casefold()
    if not normalized:
        return "empty" if value == "" else "whitespace"
    if normalized.rstrip(".!?") in {"image", "photo", "picture"}:
        return "generic"
    if unquote(unquote(normalized)).endswith((".jpg", ".jpeg", ".png", ".webp", ".svg", ".gif", ".avif")):
        return "filename"
    return "text"


def name_check(ax, scope):
    if not ax.get("available"):
        return {"scope": scope, "status": "unknown", "summary": "Browser name evidence is unavailable."}
    if ax.get("ignored"):
        return {"scope": scope, "status": "inapplicable", "summary": "This node is excluded from Chromium's accessibility tree."}
    role = ax.get("role", "")
    allowed = {"image", "img"} if scope == "image_name" else {"link", "button"}
    if role not in allowed:
        return {"scope": scope, "status": "inapplicable", "summary": f"The browser exposes role {role or 'unknown'}, outside this name check."}
    if (ax.get("name") or "").strip():
        return {"scope": scope, "status": "passed", "summary": "The browser computed a non-empty name. Its quality still needs checking."}
    return {"scope": scope, "status": "failed", "summary": f"The browser exposes a {role} with an empty accessible name."}


def assess(record):
    record["engine_version"] = ENGINE_VERSION
    record["alt_kind"] = alt_kind(record.get("alt"))
    image_check = name_check(record.get("image_ax", {}), "image_name")
    checks = [image_check]
    if record.get("control_ref"):
        checks.append(name_check(record.get("control_ax", {}), "control_name"))
    record["checks"] = checks
    record["findings"] = [
        {"id": f'{record["id"]}:{check["scope"]}', "check": check["scope"], "summary": check["summary"],
         "basis": "Chromium accessibility tree", "remedy": "Give the control a name that communicates its action or destination." if check["scope"] == "control_name" else "Provide an appropriate text alternative or correctly mark decorative content."}
        for check in checks if check["status"] == "failed"
    ]
    reasons = []
    if record.get("layout_visible"):
        kind = record["alt_kind"]
        if kind in {"filename", "generic"}:
            reasons.append(f"The alt resembles a {kind}; assess whether it communicates the image's purpose.")
        if kind in {"missing", "empty", "whitespace"}:
            reasons.append("Check whether the image is decorative, redundant, or conveys information not provided in text.")
        else:
            reasons.append("Check whether the text alternative matches the image's relevant information or function.")
        if record.get("image_ax", {}).get("ignored"):
            reasons.append("The rendered image is excluded from the accessibility tree; check whether that is intentional.")
    record["content_review"] = {"status": "not_reviewed", "reasons": reasons}
    record["triage"] = "finding" if record["findings"] else "review" if reasons else "not_applicable"
    return record


def summary(run):
    rows = run["images"]
    return {
        "discovered": run["discovered"], "inventoried": len(rows),
        "rendered": sum(bool(r.get("layout_visible")) for r in rows),
        "name_evidence_available": sum(bool(r.get("image_ax", {}).get("available")) for r in rows),
        "structural_findings": sum(len(r.get("findings", [])) for r in rows),
        "images_with_findings": sum(bool(r.get("findings")) for r in rows),
        "visual_captures": sum(r.get("capture_status") == "captured" for r in rows),
        "visual_notes": sum(bool(r.get("visual_notes")) for r in rows),
        "content_not_reviewed": sum(r.get("content_review", {}).get("status") == "not_reviewed" and bool(r.get("layout_visible")) for r in rows),
    }
