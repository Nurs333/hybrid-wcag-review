# Audit of unsupported local passes

A supplied browser scan of the public Breka homepage used Qwen3-VL-2B, prompt `local-json-v4`, on Apple MPS. It found 39 image elements and inspected the first 12. Ten captures received model assessments; two were marked not visible. All ten model decisions were pass, nine model contexts were truncated, and seven passes conflicted with rule flags. The ten requests took 255.4 seconds in total, with individual recorded times of 16.2–38.0 seconds. This confirms MPS execution, not model accuracy.

The original scan and its local paths/reviews are not distributed with the repository. The following patterns motivated generic regressions:

| Pattern | Observed problem | v5 response |
| --- | --- | --- |
| Filename-like alt | An explanation asserted descriptive words that were not in the actual alt. | Keep the exact alt and its filename state explicit; a filename alone cannot substantiate a pass. |
| Empty-alt timeline | The model described years and addresses in the image and treated their visual presence as sufficient. No text equivalent was captured. | Require captured textual support or explicit decorative semantics before accepting a pass. Otherwise retain uncertainty. |
| Empty-alt image-only links | The model called linked pastry photos non-functional decoration. Category captions were outside their links. | Keep control naming separate from sibling captions; do not accept a pass without name evidence. |
| Long source sets, CSS and tracking attributes | Prefix clipping discarded useful structure while repeating implementation markup. | Compact semantic HTML before applying context limits. |

[W3C functional-image guidance](https://www.w3.org/WAI/tutorials/images/functional/) distinguishes an image's visual subject from the purpose and naming of its enclosing control. A nearby caption is not automatically a link's accessible name. The validation code checks available evidence; it does not implement the complete browser accessible-name algorithm.

## Scope of the fix

`local-json-v5` asks for an exact `supporting_text` quotation in addition to the decision, reason and evidence. The decoder restricts that quotation to captured text choices, and the validator checks it against captured alternatives, control-name evidence and nearby text. It preserves `model_decision` and `model_reason`, adds `validation_issues`, and changes an unsupported pass to uncertain. It does not turn every filename or empty alt into an issue.

An empty-alt image can legitimately be decorative or redundant. The conservative validator can abstain on such images when their purpose is not evidenced in the capture. A matching quotation also does not prove that the text is equivalent to the picture. Full evaluation therefore needs raw model, validated model, abstention/coverage, and combined-policy metrics separately. The benchmark command now reports those separately; no improved benchmark accuracy is claimed here.

The original scanner, rule module, OpenAI request module and saved benchmark results remain frozen. Cache identities include the v5 context, schema and validation policy. Existing v4 responses are retained but are not reused as v5 judgments. Updates require rerunning local assessments; the model weights do not change or require a fresh download.

## Verification

The software suite passes 62 tests. New cases cover unnamed links with outside captions, valid inside-link text and ARIA labels, valid logo alt and title alternatives, generic/filename support, empty-alt timelines, explicit presentation semantics, actual equivalent text, markup compaction, cache invalidation and separate raw/validated metrics. They are software regressions with proposed expectations, not an independently annotated accuracy benchmark.

A separate CPU diagnostic uses the saved DOM facts and freshly downloaded public source images for a timeline, a pastry link and the logo. These source images are not the original browser screenshots and have not been vendored. [Recorded inputs, source hashes and raw outputs](local-v5-diagnostics.json) document the actual checks. This small convenience sample was used during debugging; it cannot establish generalization or a website-wide WCAG verdict. No OpenAI calls are made by these local checks.


| CPU diagnostic | Raw model | Validated result | Elapsed |
| --- | --- | --- | ---: |
| Timeline, empty alt, no captured equivalent text | Pass | Uncertain: unsupported quotation | 69.6 s |
| Image-only pastry link, empty alt, no captured name | Issue | Issue | 52.0 s |
| Linked logo with its business name in alt | Pass | Pass | 73.7 s |

The timeline demonstrates a remaining model error caught by validation, not a corrected raw model judgment. The linked-photo explanation still focuses on the empty description rather than clearly explaining link naming. Raw answers are retained for that reason. A supported quotation establishes its source, not whether the entire assessment is correct. These three checks do not establish a new accuracy score.
