"""Streamlit entry point for URL scans and the existing development reviewer."""

from pathlib import Path
import json
import os

import streamlit as st

from ai_check import DEFAULT_MODEL, assessment_key, resolve_image_path
import review_store
from website_checker import pending_ai_records, run_ai, scan_in_worker


FOLDER = Path(__file__).resolve().parent
OPTIONS = ["pass", "issue", "uncertain"]
LABELS = {
    "pass": "Pass", "issue": "Issue", "uncertain": "Uncertain",
    "potential_issue": "Rule flag", "needs_review": "Awaiting review",
    "not_visible": "Not visible",
}


def review_form(key, previous):
    selected_index = OPTIONS.index(previous["decision"]) if previous else None
    with st.form(key):
        decision = st.radio("Your decision", OPTIONS, index=selected_index, horizontal=True)
        with st.expander("Add an optional note"):
            notes = st.text_area("Reviewer notes", value=previous["notes"] if previous else "")
        submitted = st.form_submit_button("Save review", type="primary")
    return submitted, decision, notes


def evidence_panel(task, result):
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("Image")
        if task.get("image_path"):
            try:
                st.image(str(resolve_image_path(task)), width=450)
            except FileNotFoundError:
                st.info("Image unavailable. Capture the page again to refresh its evidence.")
        else:
            st.info(task.get("capture_error", "No image capture available."))
        st.write("**Alt text**")
        st.code(repr(task.get("alt")), language=None)
        if task.get("src"):
            with st.expander("Image source"):
                st.code(task["src"], language=None)
    with right:
        st.subheader("Assessment")
        st.write("**Decision**", LABELS.get(result["decision"], result["decision"]))
        st.write("**Source**", result.get("source", "AI"))
        st.write(result.get("reason", ""))
        for item in result.get("evidence", []):
            st.write("• " + item)
        if task.get("ai_error"):
            st.warning(f'AI request failed ({task["ai_error"]}). This case remains available for human review or retry.')
        if task.get("context_truncated"):
            st.info("The surrounding HTML was truncated. More page context may be needed.")
        with st.expander("Surrounding text"):
            st.text(task.get("nearby_text", ""))
        with st.expander("Inspect surrounding HTML"):
            st.code(task.get("context_html", ""), language="html")
        with st.expander("Inspect image HTML"):
            st.code(task.get("image_html", ""), language="html")


def show_development():
    tasks = json.loads((FOLDER / "ai_tasks.json").read_text(encoding="utf-8"))
    results = json.loads((FOLDER / "ai_results.json").read_text(encoding="utf-8"))
    tasks_by_page = {task["page"]: task for task in tasks}
    results_by_page = {result["page"]: result for result in results}
    available = sorted(tasks_by_page.keys() & results_by_page.keys())
    if not available:
        st.info("Run the development preparation and AI scripts to populate this screen.")
        return
    reviews = review_store.benchmark_reviews()
    page = st.selectbox("Choose a development case", available)
    st.caption(f'{sum(name in reviews for name in available)} of {len(available)} cases reviewed')
    result = results_by_page[page]
    evidence_panel(tasks_by_page[page], result)
    submitted, decision, notes = review_form(f"development_{page}", reviews.get(page))
    if submitted:
        if decision is None:
            st.warning("Choose a decision before saving.")
        else:
            review_store.save_benchmark_review(page, decision, notes, result)
            st.session_state["saved_notice"] = f"Review saved for {page}."
            st.rerun()


def show_scan_results(run):
    st.subheader(run["title"])
    st.caption(run["url"])
    records = run["images"]
    counts = st.columns(4)
    counts[0].metric("Image elements found", run["images_found"])
    counts[1].metric("Inspected", len(records))
    counts[2].metric("Issue flags", sum(record["decision"] in {"issue", "potential_issue"} for record in records))
    counts[3].metric("Awaiting review", sum(record["decision"] in {"needs_review", "uncertain"} for record in records))
    if run["images_found"] > len(records):
        st.info(f'This scan inspected the first {len(records)} image elements. Increase the image limit for wider coverage.')
    if not records:
        st.info("No top-level <img> elements were found. CSS backgrounds and images inside frames are outside this scan's coverage.")
        return
    candidates = pending_ai_records(run)
    uncached = 0
    for record in candidates:
        try:
            uncached += record.get("ai_result", {}).get("assessment_key") != assessment_key(record)
        except OSError:
            pass
    if uncached:
        st.caption(f'AI checks will send {uncached} captured images and their surrounding HTML to OpenAI using API credit. Model: {DEFAULT_MODEL}.')
        if not os.environ.get("OPENAI_API_KEY"):
            st.info("Set OPENAI_API_KEY in the terminal, then restart Streamlit to enable AI checks.")
        if st.button(f"Run AI on {uncached} images", disabled=not os.environ.get("OPENAI_API_KEY"), type="primary"):
            progress = st.progress(0, text="Evaluating captured images…")
            run_ai(run, progress=lambda done, total: progress.progress(done / total, text=f"AI check {done} of {total}"))
            st.session_state["website_scan"] = run
            st.rerun()
    else:
        st.caption("Available AI judgments are cached for these image captures and this prompt.")

    reviews = review_store.website_reviews(run["scan_id"])
    table = []
    for record in records:
        ai_result = record.get("ai_result", {})
        assessment_id = ai_result.get("response_id") or record.get("rule_reason", "")
        review = reviews.get(record["image_key"])
        current_review = review if review and review["assessment_id"] == assessment_id else None
        table.append({
            "Image": record["image_key"],
            "Alt": "Missing" if record.get("alt") is None else record["alt"] or "(empty)",
            "Assessment": LABELS[record["decision"]],
            "Source": record["source"],
            "Human decision": current_review["decision"] if current_review else "Pending",
        })
    st.dataframe(table, hide_index=True, width="stretch")
    report = dict(run)
    report["human_reviews"] = reviews
    report.pop("run_path", None)
    st.download_button("Download scan report", json.dumps(report, indent=2, ensure_ascii=False), file_name=f'image-accessibility-{run["scan_id"][:8]}.json', mime="application/json")

    selected = st.selectbox("Inspect an image", [record["image_key"] for record in records], key=f'image_{run["scan_id"]}')
    record = next(record for record in records if record["image_key"] == selected)
    result = record.get("ai_result") or {
        "decision": record["decision"], "reason": record.get("rule_reason", ""),
        "evidence": record.get("rule_flags", []), "source": record["source"],
    }
    evidence_panel(record, result)
    assessment_id = result.get("response_id") or record.get("rule_reason", "")
    previous = reviews.get(selected)
    if previous and previous["assessment_id"] != assessment_id:
        st.info("A previous review belongs to an earlier assessment. Review the updated evidence before saving again.")
        previous = None
    submitted, decision, notes = review_form(f'website_{run["scan_id"]}_{selected}_{assessment_id}', previous)
    if submitted:
        if decision is None:
            st.warning("Choose a decision before saving.")
        else:
            review_store.save_website_review(run["scan_id"], selected, decision, notes, assessment_id)
            st.session_state["saved_notice"] = f"Review saved for {selected}."
            st.rerun()


def show_website():
    st.caption("Inspect image alternatives and image-based controls on one public webpage.")
    with st.form("scan_url"):
        url = st.text_input("Website URL", placeholder="https://www.example.com/page")
        left, right = st.columns(2)
        limit = left.number_input("Maximum images", min_value=1, max_value=100, value=12)
        mode = right.selectbox("Capture mode", ["Browser", "HTML"])
        st.caption("Browser loads JavaScript and scrolls for lazy images. HTML downloads source images from the initial markup.")
        scan = st.form_submit_button("Scan webpage", type="primary")
    if scan:
        try:
            with st.spinner("Loading the page and collecting image evidence…"):
                run = scan_in_worker(url, int(limit), mode.lower())
            st.session_state["website_scan"] = run
        except Exception as error:
            st.error(f"The page could not be captured. {error}")
            if mode == "Browser":
                st.info("Install Chromium with `python -m playwright install chromium`, or select HTML mode for an initial source scan.")

    saved = sorted((FOLDER / "runs").glob("*/scan.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if saved:
        with st.expander("Open an earlier scan"):
            names = {str(path): f'{json.loads(path.read_text(encoding="utf-8")).get("title", "Scan")} · {path.parent.name[:8]}' for path in saved}
            path = st.selectbox("Saved scan", list(names), format_func=names.get)
            if st.button("Open saved scan"):
                run = json.loads(Path(path).read_text(encoding="utf-8"))
                run["run_path"] = path
                st.session_state["website_scan"] = run
    run = st.session_state.get("website_scan")
    if run:
        if run["status"] == "capture_failed":
            st.warning("This capture stopped early. The report contains the image evidence saved before the failure.")
        show_scan_results(run)


st.set_page_config(page_title="Image Accessibility Review", layout="wide")
review_store.initialize()
st.title("Image Accessibility Review")
if "saved_notice" in st.session_state:
    st.success(st.session_state.pop("saved_notice"))
section = st.radio("Workspace", ["Website scan", "Development cases"], horizontal=True)
if section == "Website scan":
    show_website()
else:
    show_development()
