"""Evidence-first local interface. No account or mandatory labeling workflow."""

from datetime import datetime, timezone
import json
import os

import streamlit as st

from . import capture, demo, storage, vision
from .facts import summary
from .report import html_report


def _start(url=None, captures=12, demonstration=False):
    with st.status("Opening Chromium and collecting browser evidence…", expanded=True) as status:
        progress = st.empty()
        def update(stage, current, total):
            progress.caption(f'{"Reading names" if stage == "names" else "Capturing images"}: {current} / {total}')
        try:
            run = capture.scan_in_worker(url, captures, markup=demo.page() if demonstration else None, progress=update)
            st.session_state["scan"] = run
            status.update(label="Capture complete", state="complete", expanded=False)
        except Exception as error:
            status.update(label="Capture could not complete", state="error")
            st.error(str(error))
            st.caption("For a missing browser, run: python -m playwright install chromium. Other failures may be page or network errors.")


def _inspector(run, row):
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        st.subheader("Captured image")
        if row.get("capture_file"):
            try:
                st.image(str(storage.image_path(run, row)), width="stretch")
            except OSError:
                st.info("This saved capture is unavailable.")
            if row.get("capture_partial"):
                st.warning("The capture shows only the visible portion of this element.")
        else:
            st.info(f'Capture: {row["capture_status"].replace("_", " ")}. Its name evidence is listed separately.')
        st.caption(f'Element: {row["tag"] if "tag" in row else "unknown"} · Alt category: {row["alt_kind"]}')
        st.code("(missing attribute)" if row.get("alt") is None else repr(row["alt"]), language=None)
    with right:
        st.subheader("Browser evidence")
        for check in row["checks"]:
            title = "Image name" if check["scope"] == "image_name" else "Enclosing control name"
            if check["status"] == "failed":
                st.error(f'{title}: missing')
            elif check["status"] == "passed":
                st.success(f'{title}: present')
            else:
                st.info(f'{title}: {check["status"]}')
            ax = row.get("image_ax" if check["scope"] == "image_name" else "control_ax", {})
            st.caption(check["summary"])
            if ax.get("name"):
                st.write(ax["name"])
        st.markdown("**Content quality: not automatically decided**")
        for reason in row["content_review"]["reasons"]:
            st.caption(reason)
        with st.expander("Naming sources and captured context"):
            st.json({"image": row.get("image_ax"), "control": row.get("control_ax"),
                "caption": row.get("caption"), "nearby_text": row.get("nearby_text"),
                "captured_at": row.get("name_snapshot_at")})
            st.code(row.get("markup", ""), language="html")
    st.divider()
    st.subheader("Optional visual assistant")
    st.caption("It describes the captured pixels without seeing the alt text or page HTML. These notes can be wrong; they cannot clear a browser finding or approve content quality.")
    engine = st.selectbox("Observation engine", ["Local · Qwen3-VL-2B", "OpenAI · paid API"], key="engine")
    provider = "local" if engine.startswith("Local") else "openai"
    if provider == "local":
        st.caption("Runs on your computer. First use downloads approximately 4 GB of pretrained weights from Hugging Face. No API fallback; allow a few minutes on CPU.")
    else:
        st.caption(f'Clicking sends this captured image to OpenAI using your API credit. Model: {vision.identity("openai")["model"]}.')
    disabled = not row.get("capture_file") or (provider == "openai" and not os.environ.get("OPENAI_API_KEY"))
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        st.info("Set OPENAI_API_KEY in the terminal that launches Streamlit, then restart it.")
    if st.button("Describe this image", disabled=disabled, type="primary"):
        try:
            with st.spinner("Generating visual notes…"):
                vision.add_notes(run, row, provider)
        except Exception as error:
            st.error(str(error))
    if row.get("visual_notes"):
        notes = row["visual_notes"]
        st.warning("Model observations — unverified")
        st.write(notes["observation"]["scene"])
        if notes["observation"]["visible_text"]:
            st.markdown("**Text guesses · may be hallucinated**")
            st.write(" · ".join(notes["observation"]["visible_text"]))
        st.caption(notes["observation"]["limitations"] or "The model reported no limitations; this is not a confidence guarantee.")
        with st.expander("Model provenance"):
            st.json({key: value for key, value in notes.items() if key != "observation"})
    with st.expander("Record your own content decision (optional)"):
        st.caption("Pass means relevant information or function is conveyed by an alternative or equivalent text. Issue means a specific missing or misleading alternative. Choose uncertain when intent or context is unresolved.")
        decisions = ["uncertain", "issue", "pass"]
        prior = row.get("review", {}).get("decision", "uncertain")
        decision = st.radio("Your assessment", decisions, index=decisions.index(prior), horizontal=True, key=f'decision_{run["id"]}_{row["id"]}')
        note = st.text_input("Note (optional)", value=row.get("review", {}).get("note", ""), key=f'note_{run["id"]}_{row["id"]}')
        if st.button("Save my decision"):
            row["review"] = {"decision": decision, "note": note, "at": datetime.now(timezone.utc).isoformat()}
            storage.save(run)
            st.success("Decision saved with this capture.")


def main():
    st.set_page_config(page_title="AltReview · image accessibility evidence", page_icon="◈", layout="wide")
    st.markdown("""<style>.block-container{max-width:1250px;padding-top:2.7rem}h1{letter-spacing:-.04em}div[data-testid='stMetric']{background:#f2f5fb;border-radius:12px;padding:16px}div[data-testid='stSidebar']{background:#f6f8fc}</style>""", unsafe_allow_html=True)
    st.caption("ALTREVIEW / BROWSER EVIDENCE FIRST")
    st.title("See what assistive technology gets.")
    st.write("Find missing image and link names, inspect the captured pixels, and keep visual judgment separate from structural evidence.")
    with st.sidebar:
        st.header("New scan")
        with st.form("scan_form"):
            url = st.text_input("Public page URL", placeholder="https://example.com")
            captures = st.slider("Visual capture budget", 1, 50, 12)
            st.caption("Names are inspected for up to 300 top-level image elements, even when fewer screenshots are captured.")
            submitted = st.form_submit_button("Scan page", type="primary", width="stretch")
        if submitted:
            _start(url, captures)
        if st.button("Try the built-in demo", width="stretch"):
            _start(captures=12, demonstration=True)
        paths = storage.history()
        if paths:
            labels = {}
            for path in paths[:30]:
                try:
                    prior = storage.load(path)
                    when = datetime.fromisoformat(prior["created_at"]).astimezone().strftime("%b %d, %H:%M")
                    labels[str(path)] = f'{when} · {prior["title"][:28]}'
                except (ValueError, OSError, KeyError):
                    continue
            selected = st.selectbox("Saved captures", list(labels), format_func=labels.get)
            if st.button("Open capture", disabled=not labels):
                try:
                    st.session_state["scan"] = storage.load(selected)
                except (ValueError, OSError) as error:
                    st.error(str(error))
        st.divider()
        st.caption("One page snapshot in Chromium. CSS backgrounds, canvas content, frames, other pages, and full WCAG conformance are outside this scan.")
    run = st.session_state.get("scan")
    if not run:
        st.info("Start with the demo: no API key, model download, or reviewer account required.")
        a, b, c = st.columns(3)
        a.markdown("**1 · Browser facts**\n\nNames come from Chromium's accessibility tree, including ARIA, titles, and text inside links.")
        b.markdown("**2 · Specific findings**\n\nAn empty name is a structural finding. A filename or an empty alt gets a content review prompt.")
        c.markdown("**3 · Optional visual notes**\n\nUse a local model to describe pixels. Keep its observations separate from verified browser facts.")
        return
    st.subheader(run["title"])
    st.caption(run["url"])
    count = summary(run)
    cols = st.columns(4)
    for col, label, value in zip(cols, ["Elements inventoried", "With browser name evidence", "Images with findings", "Visual captures"],
        [f'{count["inventoried"]} / {count["discovered"]}', count["name_evidence_available"], count["images_with_findings"], count["visual_captures"]]):
        col.metric(label, value)
    st.caption(f'{count["content_not_reviewed"]} rendered images have no automated content verdict. A present name is not proof that its description is useful.')
    for warning in run.get("warnings", []):
        st.warning(warning)
    if not run["images"]:
        st.info("No supported image elements were found. This does not mean the page contains no visual content.")
        return
    mode = st.radio("Show", ["All images", "Structural findings", "Content review"], horizontal=True)
    rows = [r for r in run["images"] if mode == "All images" or (mode == "Structural findings" and r["findings"]) or (mode == "Content review" and r["layout_visible"])]
    if rows:
        st.dataframe([{"Image": r["id"], "Image name": r.get("image_ax", {}).get("name", ""),
            "Control name": r.get("control_ax", {}).get("name", ""),
            "Browser findings": len(r["findings"]), "Alt": r["alt_kind"], "Capture": r["capture_status"],
            "Content": r.get("review", {}).get("decision", "Not reviewed")} for r in rows], hide_index=True, width="stretch")
        selected_id = st.selectbox("Inspect image", [r["id"] for r in rows])
        _inspector(run, next(r for r in rows if r["id"] == selected_id))
    else:
        st.info("No images match this filter.")
    st.divider()
    left, right = st.columns(2)
    left.download_button("Download evidence report · HTML", html_report(run), file_name=f'altreview-{run["id"][:8]}.html', mime="text/html", width="stretch")
    right.download_button("Download raw evidence · JSON", json.dumps(run, ensure_ascii=False, indent=2), file_name=f'altreview-{run["id"][:8]}.json', mime="application/json", width="stretch")
