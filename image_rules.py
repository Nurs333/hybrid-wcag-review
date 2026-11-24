"""Small, explainable rule flags shared by fixtures and URL scans."""


def apply_rules(record):
    record["rule_result"] = "needs_review"
    record["rule_reason"] = "Requires further evaluation."
    record["rule_flags"] = []

    alt = record.get("alt")
    control_text = (record.get("control_text") or "").strip()
    control_label = (record.get("control_aria_label") or "").strip()
    control_reference = (record.get("control_labelledby_text") or "").strip()
    image_label = (record.get("image_aria_label") or "").strip()
    image_reference = (record.get("image_labelledby_text") or "").strip()
    flags = record["rule_flags"]

    # Hidden/presentational images require a contextual judgment about purpose.
    if record.get("aria_hidden") or record.get("role") in {"none", "presentation"}:
        record["rule_reason"] = "Check whether the image is intentionally redundant."
        return record

    if alt is None and not image_label and not image_reference:
        flags.append("Image has no alt attribute.")

    empty_alt = alt is not None and alt.strip() == ""
    if (
        record.get("inside_control")
        and empty_alt
        and not control_text
        and not control_label
        and not control_reference
        and not record.get("control_other_image_alt")
        and not image_label
        and not image_reference
    ):
        flags.append("Image has empty alt, and its enclosing control has no name evidence.")

    normalized_alt = (alt or "").strip().casefold()
    if normalized_alt.rstrip(".!?") in {"image", "photo", "picture"}:
        flags.append("Alt text is only a generic image label.")
    elif normalized_alt.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")):
        flags.append("Alt text appears to be a filename.")

    if flags:
        record["rule_result"] = "potential_issue"
        record["rule_reason"] = " ".join(flags)
    return record
