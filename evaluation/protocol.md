# Public-image evaluation protocol

Status: collection and reference labeling tools are available. No new accuracy results are claimed.

## Frozen baseline

The original scanner, model prompt, and rule policy are preserved on the GitHub branch [`baseline-v1`](https://github.com/Nurs333/hybrid-wcag-review/tree/baseline-v1), at commit `70eb6b1a5c051d61e682cd8bd4e91f5e71e2b28e`.

`python web_evaluation.py freeze` records SHA-256 hashes of the scanner, prompt implementation, rules, and source list. Collection and scoring reject changed engine files, captures, or dataset contents. Keep this experiment unchanged after inspecting predictions. Improvements belong to a new experiment with fresh images.

## Sample

`sources.json` fixes the source order before labels or predictions. The target is 50 images, at most five per final page hostname, drawn from up to 12 pages. Sources include cafes, museums, a library, government, universities, retail, and tourism. The previously discussed 49th Parallel page and the synthetic benchmark are excluded.

Take the first eligible image elements in DOM order: successfully captured, visible in browser mode, and at least 40 pixels in each dimension. Exclude exact duplicate captured bytes. Stop at the target. Capture only the first 12 image elements per source. Record blocked sites, capture failures, and excluded cases. Retain a shortfall rather than silently replacing sources after seeing outputs. Exact hashes do not detect visually similar or differently cropped duplicates; inspect that limitation when interpreting results.

This is a convenience sample with site clusters. It is neither a random web sample nor a balanced issue/pass benchmark. A high number of passes can inflate simple accuracy. Report class counts, coverage, and per-site counts alongside any metrics.

Use browser mode for the planned evaluation. HTML mode is available for collection troubleshooting and source-only pilots; it does not establish rendered visibility. Do not merge capture modes into one headline result.

## Reference labeling

Use `label_web_images.py` before running model predictions. It reads the image, alt, captured context, and naming evidence, but never loads predictions or displays rule flags. The reviewer ID can be a pseudonym. Notes are optional; evidence notes are encouraged for issues and uncertain cases.

1. Identify the image's information or function in this context.
2. Check whether alt or equivalent accessible text conveys it.
3. Inspect control naming and hidden-state evidence when relevant.
4. Choose a decision without consulting automated output.

| Label | Definition |
| --- | --- |
| Pass | Relevant information/function is adequately conveyed. Decorative or redundant images can have empty alt. A description need not reproduce every detail. |
| Issue | Captured evidence supports a specific missing, misleading, or inadequate alternative, or an inadequately named image-based control. |
| Uncertain | Necessary purpose, page context, hidden state, animation, or naming evidence cannot be established. |

These labels answer an image-level question; they do not certify page-level WCAG conformance. A reviewer may consult the original page for missing context, recording that fact in notes; the site may have changed since capture. Do not guess the intended purpose of promotional artwork from pixels alone.

Seal the complete labels before predictions. Record whether the reviewer is the project author or external and whether any model results were already seen. External expertise should be described accurately; an external friend is not automatically an accessibility expert. The software records order and self-reports, not proof of reviewer independence. Assisted labels remain useful but must be reported as assisted.

For a stronger follow-up study, obtain a second independent review and adjudicate disagreements before revealing predictions. The current tooling allows multiple reviewer IDs but does not claim inter-rater agreement or implement adjudication.

## Three approaches

- **Rules:** issue for a candidate rule flag; otherwise uncertain. Silence is not treated as a pass.
- **AI:** assess every case once using the frozen prompt and recorded model. Successful calls are reused; failed calls can be retried.
- **Hybrid:** issue for a rule flag; otherwise reuse the same case's AI decision.

The comparison runs AI on every case to obtain an AI-only baseline. Hybrid model usage is calculated as a subset of those calls. It is a counterfactual resource estimate, not a separate deployment's measured cost or latency. API errors remain unresolved and are counted. Token usage and successful call duration are recorded; retry history and failed-request usage are not billing totals. Model output can vary across runs; record the returned model IDs and preserve outputs.

## Metrics

Score only issue/pass references for binary metrics; report uncertain reference counts separately. Never turn unknown or API-error cases into passing references.

- Precision = TP / (TP + FP).
- End-to-end issue recall = TP / (TP + FN + uncertain predictions on issue references).
- Coverage = decisive predictions / all issue/pass references.
- Selective accuracy = correct decisive predictions / decisive predictions.
- Correct fraction of all labeled cases = (TP + TN) / all issue/pass references.

Zero denominators are `null`, not perfect scores. Rules-only coverage may be low by design; show recall and abstentions alongside precision. Do not compare selective accuracy without its coverage. Inspect `failure_review` for disagreements, unresolved cases, and API errors.

## Run locally

From the installed project environment:

```bash
python web_evaluation.py freeze
python web_evaluation.py collect
python -m streamlit run label_web_images.py --server.address 127.0.0.1
```

Complete and seal the reference labels, then stop the labeling app with Control+C. With `OPENAI_API_KEY` set in the terminal:

```bash
python web_evaluation.py predict --allow-api
python web_evaluation.py score --labels evaluation/local/labels/REVIEWER_ID.json
```

The prediction step uses paid OpenAI API calls for every collected image. The collector and reference reviewer do not call the model. Local dataset captures, reviewer files, model predictions, and `comparison.json` are stored under `evaluation/local/` and excluded from Git. Do not commit third-party captures or reviewer notes by accident. Publish only a deliberately reviewed report with accurate provenance and necessary permissions.
