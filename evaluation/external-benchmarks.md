# External labeled benchmarks

This workflow uses existing references. It does not require new manual image labeling. It complements the synthetic examples; it does not replace their original results or establish general web accuracy.

## Sources and scope

| Source | Reference type | Imported subset |
| --- | --- | --- |
| [W3C ACT cases](https://www.w3.org/WAI/standards-guidelines/act/report/testcases/) | Expected result for an individual accessibility rule | Source-HTML, single-`img` cases for `23a2a8` and `qt1vmo`, with supported static markup and downloadable image sources |
| [ASSETS 2026 dataset](https://zenodo.org/records/21359354) | Human quality ratings of the original alternative text | Groups with absolute downloadable image URLs and static source images |

The [ASSETS paper](https://doi.org/10.1145/3797867.3829029) describes the rating procedure and distinguishes repeated assessments from distinct images. The importer groups rows by historical page identifier, image URL, and original alternative. It uses at most one consistent rating per reviewer per group. Raw reviewer identifiers are not included in public results.

The included [import summary](external-results.json) records the executed local import and rules baseline. Source hashes identify the downloaded catalog and CSV. That earlier snapshot contains no paid AI results. The subsequent [model-run results](external-model-results.json) are recorded separately below.

## Recorded model run

The model run completed 11 ACT and 38 ASSETS requests with zero API errors. The engine and original rule routing were preserved.

| Subset | Rules only | AI only | Hybrid |
| --- | --- | --- | --- |
| ACT: 6 pass, 5 issue references | 2 true issue flags, 1 false alarm, 8 abstentions | 5 true issue decisions, 6 true passes; 11/11 agreement | 5 true issue decisions, 5 true passes, 1 false alarm; 10/11 agreement |
| ASSETS: 36 issue, 2 uncertain references | No issue flags; all binary-reference cases deferred | 33 issues detected, 2 passed despite issue references, 1 uncertain; 33/36 end-to-end issue recall (91.7%) | Same as AI-only because no rule flags bypassed AI |

The two reference-uncertain ASSETS cases are excluded from binary metrics, regardless of model decisions. There are no passing references in that subset, so zero observed false alarms does not establish specificity or false-positive performance.

For ACT, AI-only precision and issue recall are both 100% on these 11 cases. Hybrid issue recall is 100%, but precision is 5/6 (83.3%) because of the inherited title-name false alarm. These are small rule-reference regression results, not general accessibility accuracy estimates. ASSETS AI coverage among the 36 binary references is 35/36 (97.2%).

The comparison does **not** demonstrate that the current hybrid policy improves on AI-only: it loses one ACT case and produces the same ASSETS decisions. The observed failure motivates evaluating a revised rule-routing policy on a separate experiment. Current references and results have not been changed to improve the score.

Successful calls recorded 33,869 input tokens and 4,808 output tokens across both datasets. Their durations sum to approximately 157.5 seconds. This is not an independent hybrid latency or billing measurement; the comparison deliberately requested AI outputs for all cases.

## W3C outcome handling

The source catalog has `passed`, `failed`, and `inapplicable` outcomes. Inapplicable cases are excluded and counted; they are never converted to passes or uncertainty. Unsupported SVG, canvas, script-dependent, styled, multi-target, hidden-state, or unavailable-image cases are also explicitly excluded. The restrictions select a narrow source-HTML regression subset, not the full ACT suite or a browser accessibility-tree implementation.

For applicable imported cases, `passed` becomes a pass reference and `failed` an issue reference **for the source rule only**. The scanner's rule flags can concern broader semantics than an ACT non-empty-name rule; agreement with those references is not full image or page conformance. Reports retain per-rule results.

Test-page titles and HTML comments are removed from model context because they can disclose expected outcomes. Case identifiers, source outcomes, and reference explanations are not model inputs.

## ASSETS rating handling

The release contains 645 rating rows covering 205 image URLs. Its image fields are not all downloadable URLs: 166 are paths to locally saved webpage assets. We do not guess missing base URLs or replace historical assets with current website images. The 39 absolute URLs all belong to one WIRED page; one animated image is excluded, leaving 38 imported static images in the recorded run.

The model receives the original alternative, available historical HTML/text context, and downloaded image. The CSV does not establish complete original DOM, page layout, control naming, or the distinction between absent and empty alternatives. These gaps limit conclusions. Downloaded URLs could have changed since the original study; capturing current bytes does not prove they match the original rated bytes. This subset is an availability-biased pilot, not the complete multi-domain study.

The fixed **quality proxy** mapping is:

- Ratings 1–2: issue category.
- Rating 3: uncertain category.
- Ratings 4–5: pass category.
- An issue or pass category needs a strict majority across distinct reviewers; otherwise the reference is uncertain.

This is a project-defined conversion, not a pass/fail label published by the dataset authors. Raw human ratings are retained locally for sensitivity analysis. Teacher scores, model judgments, generated alternatives, and user ratings of generated alternatives are never substituted for human ratings of the original alt.

The recorded accessible subset maps to **36 issue references, two uncertain references, and no passing references**. Consequently, this pilot can inspect issue detection and abstentions but cannot estimate specificity or a false-positive rate. Do not present a high issue recall on this subset as balanced classification accuracy.

## Local commands

Use the installed project Python environment. Preparation downloads the catalog, source CSV, supported markup, and image files. It does not call OpenAI or require Chromium.

```bash
python external_benchmarks.py prepare
python external_benchmarks.py score
```

The second command records the rules baseline and reports AI as `not_run`. To run the actual AI-only and hybrid comparisons, set `OPENAI_API_KEY` in the same terminal, then use:

```bash
python external_benchmarks.py predict --allow-api
python external_benchmarks.py score
```

Prediction makes paid requests for each prepared case; a successful case is reused, while failures remain unresolved and can be retried. The current snapshot has 49 cases across both benchmarks. Use `--dataset act` or `--dataset assets` on any command to limit its scope. Check the prepared counts for your snapshot before requesting predictions.

Inputs, references, and predictions are separate JSON files in `evaluation/external-local/act/` and `evaluation/external-local/assets/`. Prediction does not open the reference files. Input bytes, references, importer policy, model selection, and engine hashes are checked for alignment. A changed mapping or engine requires a new experiment. Preserve the existing experiment folder before collecting a new snapshot.

The report includes precision, end-to-end issue recall, coverage, abstentions, raw counts, per-case disagreements, successful token usage, and call duration. Reference-uncertain cases are counted separately from binary metrics. API failures and missing predictions never become passes. Successful-call resource totals omit failed-call usage and retry history; dollar costs are not inferred.

Public benchmarks may have appeared in model training. Treat these as external reference regression checks, not evidence of unseen-model generalization.

## Recorded baseline limitation

One imported W3C pass example has a valid accessible name via `title="W3C logo"` while omitting `alt`. The frozen baseline flags the missing attribute anyway. That is a false alarm relative to the source rule. The baseline is preserved to make the limitation visible; these results were not tuned away after examining the references.

## Citation and redistribution

- Leonardi, N., Manca, M., and Paternò, F. (2026). *Beyond LLMs: Small Multimodal Models for Semantic Accessibility Validation of Alternative Texts*. [Paper DOI](https://doi.org/10.1145/3797867.3829029). [Dataset DOI](https://doi.org/10.5281/zenodo.21359354).
- W3C Web Accessibility Initiative. [ACT Test Cases](https://www.w3.org/WAI/standards-guidelines/act/report/testcases/) and the rule pages linked by its catalog. [Referenced test-case license](https://act-rules.github.io/pages/license/).

Third-party CSVs, reviewer data, captured markup, and images are downloaded locally and excluded from Git. The repository publishes import code and aggregate derived counts, not a redistributed copy of the external datasets. The paper's license does not automatically establish licensing for every underlying website image. Consult source terms before redistributing any downloaded material.
