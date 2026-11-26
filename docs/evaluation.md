# What has actually been measured

## Browser-name regression

The included evaluation uses W3C ACT rule **23a2a8, Image has non-empty accessible name**. It includes all 18 fixtures in the pinned catalogue selection: eight expected passed, five failed, and five inapplicable. None is excluded because it is difficult or unsupported by a source-HTML heuristic.

The benchmark serves the unmodified HTML and two original source PNGs offline, at their original URLs in isolated browser contexts. All other requests are aborted. The input manifest contains SHA-256 hashes for HTML, assets, and the source catalogue. Labels live in `references.json`, which is read only after every prediction. Input or asset hash mismatches stop the benchmark. Unknown/error outcomes count in the agreement denominator.

Recorded result: **18 matched / 18 cases**, zero unknown, Chromium **141.0.7390.37**. See `evaluation/act/report.json` for actual browser roles, name sources, and ignored reasons. The exact browser is tied to Playwright 1.56.0. Setting `ALTREVIEW_BROWSER` to another executable changes the tested browser and can change results.

For this atomic rule, an applicable image can satisfy the expectation by a non-empty name or presentation semantics. Programmatically hidden nodes are inapplicable. The application's per-node inspector calls excluded nodes inapplicable to its *exposed-name* check; the benchmark adapter distinguishes presentation from hidden applicability to compare the published ACT expectation. Both preserve the raw accessibility-tree evidence.

This is a public regression suite, not proof of unseen generalization. It does not test whether a description is accurate, whether decoration is intentional, whether chart data are complete, or whether a whole page meets WCAG. A present name is not a visual-quality pass.

## Software tests

The tests render real Chromium fixtures for title alternatives, hidden ARIA label references, CSS-generated link names, sibling versus descendant captions, missing names, decorative empty alt, filename alts, hidden capture budgeting, and complete bounded inventory. Streamlit AppTest exercises demo loading, filtering, inspection, and saved optional decisions. Additional tests cover output escaping, unknown evidence, private-address rejection, storage traversal, observation cache identity, and provider failure behavior.

Mocked observer tests verify integration contracts only. They do not measure model accuracy. CI runs these tests and the pinned offline ACT fixtures without any API key or model download.

## Visual assistant

The local vision assistant is an experimental observation tool. It has no measured accessibility-classification accuracy in this rebuild. One successful inference only verifies loading, generation, parsing, and persistence; it does not establish description quality.

A future semantic benchmark should use independently labeled image-plus-page-context examples, keep a frozen test split separate from prompt development, report abstentions and false positives, and compare a structural baseline with any proposed semantic judge. Do not transplant the prototype's small synthetic or OpenAI scores onto this local observer.

### Local inference smoke test

`docs/observer-smoke.json` records a real CPU call using the pinned Qwen weights on a Breka cake image from the earlier capture investigation. It completed in 42.09 seconds with 77 output tokens. The scene broadly describes the cake, but the `visible_text` field invents object words such as "strawberry" and "plate" rather than transcribing printed text. This is a known failure, not a passing semantic test. No accessibility accuracy is claimed. Those text guesses are explicitly marked unverified in the UI.
