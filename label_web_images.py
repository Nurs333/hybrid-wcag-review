"""Reference labeling screen. Does not load rule flags or model predictions."""

from datetime import datetime, timezone
import re

import streamlit as st

from ai_check import resolve_image_path
from web_evaluation import LOCAL, fingerprint, read_json, validate_dataset, write_json

st.set_page_config(page_title="Image reference labeling", layout="wide")
st.title("Image reference labeling")
st.caption("Review the captured image and its HTML context before viewing automated assessments. A pass applies only to the image question.")
path = LOCAL / "dataset.json"
if not path.exists():
    st.info("Collect the evaluation images first: python web_evaluation.py collect")
    st.stop()
dataset = read_json(path)
try:
    validate_dataset(dataset)
except (ValueError, FileNotFoundError) as error:
    st.error(str(error))
    st.stop()
if dataset["capture_mode"] == "html":
    st.warning("Source-only pilot: rendered layout and visibility were not captured. Choose uncertain when that missing context matters.")
with st.expander("Labeling rubric", expanded=True):
    st.markdown("""
- **Pass:** the image's relevant information or function is conveyed by its alternative or equivalent available text. Empty alt can be appropriate for decorative or redundant images.
- **Issue:** the evidence supports a specific missing, misleading, or inadequate alternative, or an image-based control lacks a meaningful name.
- **Uncertain:** the image's purpose, equivalent text, control naming, animation, hidden state, or other necessary context cannot be established from this capture.

Check the image's purpose, its existing alternative, equivalent text, and any enclosing control. A description need not list every visible detail. Do not assume an image is wrong merely because alt is empty. Do not assume it passes merely because alt is present.
""")
reviewer = st.text_input("Reviewer ID", help="Use a pseudonym, letters, digits, underscores, or hyphens. Do not enter private contact details.")
if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", reviewer):
    st.info("Enter a reviewer ID to start.")
    st.stop()
label_path = LOCAL / "labels" / (reviewer + ".json")
labels = read_json(label_path) if label_path.exists() else {
    "dataset_sha256": dataset["dataset_sha256"], "reviewer": reviewer, "labels": {},
}
if labels["dataset_sha256"] != dataset["dataset_sha256"]:
    st.error("This reviewer file belongs to another dataset. Use another reviewer ID.")
    st.stop()
sealed = bool(labels.get("sealed_at"))
st.caption(f'{len(labels["labels"])} of {len(dataset["cases"])} images labeled')
if sealed:
    st.success("Reference labels are sealed. This screen will not modify them.")
    st.download_button("Download reference labels", label_path.read_bytes(), file_name=label_path.name, mime="application/json")
    st.stop()
case_id = st.selectbox("Image", [case["case_id"] for case in dataset["cases"]])
case = next(case for case in dataset["cases"] if case["case_id"] == case_id)
left, right = st.columns(2)
with left:
    st.image(str(resolve_image_path(case)), width=450)
with right:
    st.write("Existing alt attribute")
    st.code("[missing]" if case["alt"] is None else repr(case["alt"]), language=None)
    st.write("Captured surrounding text")
    st.text(case.get("nearby_text") or "[No surrounding text captured]")
    if case.get("context_truncated"):
        st.warning("Captured context was truncated; more evidence may be needed.")
    with st.expander("Image and surrounding HTML"):
        st.code(case.get("image_html") or "", language="html")
        st.code(case.get("context_html") or "", language="html")
    with st.expander("Naming and hidden-state evidence"):
        st.json({key: case.get(key) for key in ("control_type", "control_text", "control_aria_label", "control_labelledby_text", "image_aria_label", "image_labelledby_text", "aria_hidden", "role")})
    st.link_button("Original page (may have changed)", case["page"])
current = labels["labels"].get(case_id, {})
with st.form("reference_" + case_id):
    options = ["pass", "issue", "uncertain"]
    selected = st.radio("Reference decision", options, index=options.index(current["decision"]) if current else None)
    note = st.text_area("Brief evidence or missing context (optional)", value=current.get("note", ""))
    if st.form_submit_button("Save reference"):
        if selected is None:
            st.error("Choose a decision first.")
        else:
            labels["labels"][case_id] = {"decision": selected, "note": note, "saved_at": datetime.now(timezone.utc).isoformat()}
            write_json(label_path, labels)
            st.rerun()
st.divider()
st.subheader("Seal completed references")
relationship = st.selectbox("Reviewer relationship", ["Project author", "External reviewer"], index=None)
exposure = st.selectbox("Have you seen automated decisions for any images in this set?", ["No", "Yes"], index=None)
if st.button("Seal references", disabled=len(labels["labels"]) != len(dataset["cases"])):
    if relationship is None or exposure is None:
        st.error("Record the reviewer relationship and prior exposure first.")
    else:
        labels.update(relationship=relationship, automated_decisions_seen=exposure == "Yes", sealed_at=datetime.now(timezone.utc).isoformat())
        labels["labels_sha256"] = fingerprint(labels)
        write_json(label_path, labels)
        st.rerun()
