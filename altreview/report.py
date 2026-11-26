"""Portable, escaped evidence reports. Never interpret website markup as report markup."""

import base64
from html import escape
import json

from .facts import summary
from . import storage


def html_report(run):
    cards = []
    for row in run["images"]:
        picture = ""
        if row.get("capture_file"):
            try:
                encoded = base64.b64encode(storage.image_path(run, row).read_bytes()).decode("ascii")
                picture = f'<img class="capture" alt="Captured page image for {escape(row["id"])}" src="data:image/png;base64,{encoded}">'
            except OSError:
                picture = "<p>Capture unavailable in this copy.</p>"
        checks = "".join(f'<li><b>{escape(c["scope"])}</b>: {escape(c["status"])} — {escape(c["summary"])}</li>' for c in row["checks"])
        visual = row.get("visual_notes", {}).get("observation")
        notes = f'<h3>Unverified model observations</h3><pre>{escape(json.dumps(visual, ensure_ascii=False, indent=2))}</pre>' if visual else ""
        human = row.get("review", {})
        review = f'<p>Reviewer decision: <b>{escape(human.get("decision", "Not reviewed"))}</b></p>'
        cards.append(f'''<article><h2>{escape(row["id"])} · {escape(row["triage"])}</h2>{picture}
          <p>Alt: <code>{escape(repr(row.get("alt")))}</code></p>
          <p>Browser image name: <code>{escape(row.get("image_ax", {}).get("name", ""))}</code></p>
          <p>Browser control name: <code>{escape(row.get("control_ax", {}).get("name", ""))}</code></p>
          <ul>{checks}</ul><p>Content quality: {escape(row["content_review"]["status"])}</p>{review}{notes}
          <details><summary>Captured evidence</summary><pre>{escape(json.dumps(row, ensure_ascii=False, indent=2))}</pre></details></article>''')
    metrics = summary(run)
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>AltReview evidence report</title><style>
      body{{font:16px/1.6 system-ui;max-width:1040px;margin:40px auto;padding:0 24px;color:#14263d;background:#f6f8fc}}
      article{{background:white;border:1px solid #dce3ee;border-radius:14px;padding:24px;margin:20px 0;overflow:auto}}
      .capture{{max-width:420px;max-height:280px;object-fit:contain}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}
      code{{overflow-wrap:anywhere}}h1{{font-size:40px}}h2{{font-size:23px}}
      </style><h1>AltReview</h1><p>{escape(run["title"])}</p><p>{escape(run["url"])}</p>
      <p>Captured {escape(run["created_at"])} · Chromium {escape(run.get("browser_version", "unknown"))}</p>
      <p>{metrics["inventoried"]} of {metrics["discovered"]} image elements inventoried · {metrics["images_with_findings"]} images with structural findings · {metrics["visual_captures"]} visual captures</p>
      <p><strong>Scope:</strong> top-level image and enclosing link/button names in one Chromium page snapshot. A passed name check only means a non-empty accessible name. Content quality, full WCAG conformance, CSS backgrounds, frames, and other pages are not certified.</p>
      <p>{escape(' '.join(run.get('warnings', [])))}</p>{''.join(cards)}</html>'''
