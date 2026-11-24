# Evaluation notes

## Synthetic cases

The benchmark has 30 authored pages and 50 image elements. One target image per page is labeled for evaluation. There are 24 development cases (12 issue, 12 pass) and six holdout cases (three issue, three pass).

| Run | Correct issue decisions | False alarms | Missed issues | Correct passes | Total agreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original development | 12 | 4 | 0 | 8 | 20/24 |
| Revised development | 12 | 0 | 0 | 12 | 24/24 |
| Holdout | 3 | 0 | 0 | 3 | 6/6 |

Rules alone flagged seven of the 12 development issues with no false alarms. The model evaluated the other 17 development targets. Two holdout issues were flagged by rules and the remaining four holdout targets went to the model.

## Development revisions

Four passing development examples disagreed with the original model run. Inspection revealed ambiguity or incomplete alternatives. Cases 02 and 10 received more accurate descriptions; cases 24 and 28 received complete event details as real text. The prompt stayed unchanged and those cases were assessed again. The revised score applies to those revised inputs; it must not replace the original run when describing the original dataset.

Original observations, predictions, and evaluation text are retained in the `*_v1` files. Machine-specific path prefixes were removed from the publication copy without changing the image, context, prediction, or reference label content.

## Limits

- Labels are author-proposed synthetic references, not independent expert annotations.
- The holdout has only six cases and shares image assets and layout patterns with development.
- Development examples were revised after inspecting results.
- Benchmark human reviews made with the answer key are reference-guided interface checks.
- Public-page human reviews were made after model decisions were visible and discussed.
- The single public-page example is a functional case study, not an accuracy benchmark.
- A skipped image is unevaluated. A pass applies only to the inspected image question, not to page-level WCAG conformance.

## Reproduce saved evaluations

```bash
python checker.py
python prepare_ai.py
python prepare_holdout.py
python evaluate.py
python evaluate_hybrid.py
python evaluate_holdout.py
```

These commands use the stored model outputs and do not call the API. `check_all_images.py` and `check_holdout_images.py` can make paid API requests for uncached inputs.
