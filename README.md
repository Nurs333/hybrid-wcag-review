# Hybrid WCAG Review

A Python prototype for evaluating image alternatives and image-based controls on public webpages. It combines browser or HTML capture, explainable rule flags, vision-language model judgments, and saved human reviews.

A nonempty alt attribute can still describe the wrong image. This project combines inexpensive structural checks with visual assessment and a reviewer interface. Rules flag straightforward candidates; captured images without rule flags go to the model. Reviewers can inspect the image and context, save a decision, and export the report.

![A public webpage image flagged for a misleading text alternative](docs/screenshots/website-finding.png)

[Evaluation workflow](evaluation/protocol.md) · [Public webpage case study](docs/website-case-study.md) · [Evaluation notes](docs/evaluation.md) · [Third-party assets](THIRD_PARTY.md)

## Features

- Scan a public webpage through Chromium or its initial HTML.
- Inspect missing, empty, generic, and filename-like alternatives, plus image-based controls.
- Compare captured images with their alternatives and nearby context through the OpenAI API.
- Review pass, issue, and uncertain assessments with supporting evidence.
- Save reviews in SQLite and download JSON reports.
- Reproduce results on 30 synthetic cases using saved predictions.

## Run the application on macOS

Open a terminal in this project folder.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set your OpenAI key in the same zsh terminal to enable the AI button.

```bash
read -s "OPENAI_API_KEY?Paste your OpenAI API key and press Enter: "
export OPENAI_API_KEY
python -m streamlit run review_app.py --server.address 127.0.0.1
```

Rule scans and saved development-case reviews also work with the API key unset. Live AI checks use OpenAI API credit. The app displays the number of images to send before the AI button is pressed.

## Check a public webpage

1. Open **Website scan** and enter a public webpage URL.
2. Choose the image limit. The default is 12 image elements, configurable up to 100.
3. Choose **Browser** to load JavaScript and scroll for lazy images, or **HTML** to inspect the initial markup and download its image sources.
4. Click **Scan webpage**. The app captures images and page context, then runs the rules.
5. Click **Run AI** to evaluate the remaining captured images using `gpt-6.2-sol`.
6. Inspect individual findings. Human review offers `pass`, `issue`, and `uncertain`, with optional notes.
7. Download the JSON report, which includes automated evidence and saved human reviews.

A public example for a first HTML-mode scan is https://www.w3.org/WAI/tutorials/images/informative/. Try three images initially. Browser mode requires the Chromium installation above.

The command-line entry point uses the same scan and evaluation logic.

```bash
python website_checker.py https://www.w3.org/WAI/tutorials/images/informative/ --mode html --max-images 3
python website_checker.py https://example.com --mode browser --max-images 12 --ai
```

Each scan is saved beneath `runs/` with its own image captures and a `scan.json` checkpoint. Earlier scans can be reopened in the app. Each run gives image elements separate identifiers, including multiple uses of the same source image. Repeated AI checks reuse successful results when the image bytes, relevant context, prompt, and model match. Failed AI requests remain available for retry or human review. Changing the image or context invalidates its cached judgment.

HTML mode resolves relative URLs, document base URLs, common lazy-loading attributes, and source sets. Browser mode uses `currentSrc` and screenshots of rendered image elements, which also supports SVG image sources and avoids separate cross-origin image downloads. Captures retain image-level evidence. The scanner records inaccessible or failed image downloads so the report still shows their metadata and rule flags.

## What the prototype evaluates

The scanner examines top-level HTML `img` elements, their text alternatives, nearby text and HTML, and containing links or buttons. It preserves the difference between missing alt and empty alt, resolves `aria-labelledby` references, and records ARIA-hidden ancestry in browser mode. Rules flag missing alternatives, apparently unnamed image-based controls, generic labels, and filename-like descriptions. These are candidate problems for contextual verification.

AI receives the captured image and a selected context object. Reference labels and reference rationales stay in the evaluation scripts. The structured response contains a decision, reason, and supporting evidence. Unparsed responses and API failures stay unresolved.

A finding applies to the inspected image and its containing control. Full WCAG conformance also involves keyboard interaction, forms, contrast, document structure, and other checks. CSS background images, canvas content, cross-origin frame contents, and authenticated pages are outside this prototype's coverage. Browser scrolling is bounded to eight viewport steps, so long or interaction-dependent pages can require additional inspection. HTML mode uses initial source markup and cannot establish the final rendered state. Surrounding HTML is capped at 24,000 characters and truncation is recorded.

Public websites may restrict automated browsers or image downloads. Their failures are surfaced in the app. Run the app locally.

## Fresh public-image evaluation

The original system is preserved on the `baseline-v1` branch. A separate evaluation workflow collects a fixed convenience sample, records integrity hashes, and presents a reference-labeling screen without automated decisions. It compares rules-only, AI-only, and hybrid judgments on the same captured images, reporting abstentions and coverage alongside precision and recall.

```bash
python web_evaluation.py freeze
python web_evaluation.py collect
python -m streamlit run label_web_images.py --server.address 127.0.0.1
```

The target is 50 images with at most five per page hostname; blocked pages and collection shortfalls are recorded. Reference labels must be completed and sealed before scoring. Prediction is a separate paid step. The workflow records whether labels were sealed before predictions and whether the reviewer saw automated results. It does not assume an external reviewer is an expert or independent merely because a reviewer ID exists. No new accuracy score is claimed until the experiment is actually run. See the [protocol and remaining commands](evaluation/protocol.md).

## Existing synthetic benchmark

The original project includes 30 synthetic pages with 50 image elements, across 15 matched scenario pairs. Each page has one labeled target image, marked `id="target"`. Development contains 24 cases and holdout contains six cases across three separate groups. Repeated assets and related layout patterns occur across the splits.

| Experiment | Cases | Matching judgments | False alarms | Missed issues |
| --- | ---: | ---: | ---: | ---: |
| Original development run | 24 | 20 | 4 | 0 |
| Revised development run | 24 | 24 | 0 | 0 |
| Holdout run | 6 | 6 | 0 | 0 |

Rules alone flagged 7 of the 12 labeled development issues, with zero false alarms. The remaining 17 development targets were evaluated by AI. The combined original run identified all 12 issues and disagreed with four passing reference labels.

Reviewing those disagreements exposed ambiguous or incomplete passing examples. Cases 02 and 10 received more accurate visual descriptions. Cases 24 and 28 received full event details in real text. The prompt stayed the same, and those four development cases were evaluated again. The original AI responses, original observations, and original evaluation remain in the version-one files. Revised results describe the revised dataset.

These results show agreement with author-proposed synthetic reference labels. Independent expert annotation, an independent reviewer study, and real-website accuracy measurement remain future evaluation work. Human reviews entered while consulting the reference table are reference-guided UI tests. The six-case holdout is small and shares visual assets with development.

Reproduce the saved benchmark evaluation with the existing inputs and cached AI outputs.

```bash
python checker.py
python prepare_ai.py
python prepare_holdout.py
python evaluate.py
python evaluate_hybrid.py
python evaluate_holdout.py
```

The extraction step refreshes image paths after moving the folder. Cached fixture responses are included to reproduce the recorded experiment without new API calls. Fresh API evaluations are available through `check_all_images.py` and `check_holdout_images.py`; changed inputs trigger new requests.

## Project structure

| File | Responsibility |
| --- | --- |
| `review_app.py` | Website scan interface and existing development reviewer |
| `website_checker.py` | URL capture, checkpoints, live AI routing, and CLI |
| `image_rules.py` | Shared rule flags for fixture and URL inputs |
| `ai_check.py` | OpenAI request, structured result, and cache fingerprints |
| `review_store.py` | SQLite persistence for development and website reviews |
| `checker.py` | Extract the bundled local example pages |
| `prepare_ai.py`, `prepare_holdout.py` | Select unresolved benchmark targets |
| `evaluate*.py` | Compare benchmark predictions with reference labels |
| `examples/`, `assets/` | Synthetic fixture pages and local assets |
| `answer_key.json`, `answer_key.csv` | Reference labels and explanations |
| `tests/` | Focused extraction, caching, retry, persistence, and app checks |

The application creates `human_reviews.db` locally. Personal review databases are excluded from version control. Website reviews use a separate table and are scoped to the scan and image identifier. Saving a decision again updates its latest value. A changed AI response requires a fresh review of the updated assessment. Notes are optional and their control starts collapsed.

## Verification

```bash
python -m unittest discover -s tests -v
```

The automated tests cover source URL resolution, missing versus empty alt, label references, image-name evidence, transparency, context truncation, cache invalidation, partial API failures, reviewer persistence, and the Streamlit scan/review interactions. AI tests use a fake client to verify payloads, successful caching, and failure handling without API charges.

A live HTML scan was exercised against W3C's informative-images tutorial. A browser-mode scan and three real OpenAI assessments were subsequently completed on macOS against a public coffee-shop page; the exported observations and reviews are documented in the [case study](docs/website-case-study.md). The automated suite covers request construction and failure handling with a fake client, so running tests does not consume API credit.

## Dataset sources

- W3C alt decision tree — https://www.w3.org/WAI/tutorials/images/decision-tree/
- W3C informative images — https://www.w3.org/WAI/tutorials/images/informative/
- W3C functional images — https://www.w3.org/WAI/tutorials/images/functional/
- W3C complex images — https://www.w3.org/WAI/tutorials/images/complex/
- Playwright Python — https://playwright.dev/python/docs/library
- OpenAI vision input — https://developers.openai.com/api/docs/guides/images-vision
- Streamlit — https://docs.streamlit.io/

Fixture photographs and font sources are recorded in `asset_sources.json`. Font licenses are included in `assets/`. Charts, interface icons, the map, and event artwork were drawn for the synthetic dataset. Page brands and content are fictional demonstrations. Live capture files remain local to each scan.
