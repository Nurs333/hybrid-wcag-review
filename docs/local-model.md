# Local model backend

The website reviewer defaults to pretrained [Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct). This is local inference with an existing vision-language model, not a model trained or fine-tuned by this project. The weights are Apache-2.0 licensed; their revision is pinned in `local_model.py`.

## Install on an Apple Silicon Mac

Use a separate Python 3.12 environment. The optional Torch 2.8/torchvision 0.23 dependencies are pinned together; the existing Python 3.14 environment is not the supported local setup.

```bash
conda create -n wcag-local python=3.12 -y
conda activate wcag-local
python -m pip install -r requirements-local.txt
python -m playwright install chromium
python local_model.py warmup
python -m streamlit run review_app.py --server.address 127.0.0.1
```

Without Conda, create a virtual environment with an installed Python 3.12:

```bash
python3.12 -m venv .venv-local
source .venv-local/bin/activate
python -m pip install -r requirements-local.txt
```

Initial warmup requires internet access to download approximately 4–5 GB of model files. Allow additional space for dependencies and captures. The unquantized model alone needs several GB of memory plus inference buffers. A 16 GB or larger Mac is the intended starting configuration, not a measured minimum. Close memory-heavy applications and begin with one image. CPU execution is supported but can be slow. This implementation selects CUDA, then Apple MPS, then CPU according to availability. A supplied v4 scan confirms MPS execution (10 completed judgments, 16.2–38.0 seconds each), while exposing unsupported passes. This is execution evidence, not accuracy validation.

No API key is needed. Model files use the Hugging Face cache, outside the repository. After warmup, cached inference can be checked with networking disabled for Hugging Face:

```bash
HF_HUB_OFFLINE=1 python local_model.py check --image assets/office.jpg --alt "A dog playing in the snow."
```

This offline flag affects model loading, not webpage capture. Scanning a website still requires its network resources.

## Routing and caching

1. Capture image elements and their context. Record hidden elements and capture failures.
2. Run structural checks and keep their candidate flags.
3. Offer every visible, successfully captured image to the selected backend. A non-generic alt does not bypass visual review.
4. Combine model output with rule evidence. A rule flag plus model pass becomes uncertain; a model issue remains an issue. Model uncertainty or failure stays unresolved.
5. Let reviewers inspect the evidence and save a decision.

Local is the default engine. Choosing OpenAI is explicit and requires a key. Local failures never trigger a paid fallback. Earlier API results remain in a provider-specific cache when switching engines. Cache identity covers image bytes, model revision, prompt, bounded context, and image/generation limits. Human reviews are scoped to the actual combined assessment.

The default image limit still bounds how many elements are captured. Increase it for wider coverage. This does not imply that hidden or failed captures were visually assessed.

## Output and quality limits

The local model must return exactly `decision`, `reason`, `evidence`, and `supporting_text`. A pass must quote an actual captured alternative, control name, or equivalent nearby text. The decoder constrains the quotation to a per-image list of captured strings, so it cannot insert a newly invented scene description into that field. Captions outside a link are kept separate from its name evidence. [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer) constrains generated tokens to a JSON schema, including decision labels, required fields, and short explanations. The completed response is then validated separately. A token limit can still interrupt an object: malformed or truncated output is recorded as uncertain and its raw response is retained. Exceptions are retriable errors, not passes. Format constraints do not establish semantic accuracy.

Inference is deterministic greedy decoding with a 224-token cap and a 120-second soft generation budget. The time check happens between generation steps; loading, preprocessing, and a slow individual step can exceed that budget. An incomplete response stays uncertain. The image has at most a 1024-pixel long edge and a 512×512 processor pixel budget; input context is bounded to approximately 6000 characters. These limits reduce memory use but can erase small text or necessary page evidence. Truncation is recorded. The model can still hallucinate or overlook an error even when its JSON is valid. A pass is a model assessment of the image, not WCAG certification of the page.

The original OpenAI benchmark scores do not transfer to this backend. A 500M-parameter model tried during development failed the JSON/mismatched-alt smoke test and was rejected as the default. Evaluate the selected model separately before treating its decisions as reliable. Length-constrained explanations can be rough or end mid-sentence; the raw response is retained and a well-formed JSON object is not proof of a correct judgment.

## Checks recorded before v5

Cached-weight inference was exercised with `HF_HUB_OFFLINE=1` on Python 3.12 and CPU. [Inputs, raw outputs, package versions, and timing](local-smoke-results.json) are recorded separately from the external benchmarks.

| Input | Local result | Elapsed |
| --- | --- | ---: |
| Office photo described as a dog in snow | Issue | 50.2 s |
| Same photo with a matching corridor description | Pass | 82.8 s |
| Informative poster with empty alt | Uncertain: time budget interrupted JSON | 125.5 s |

These developer-selected checks were used while debugging the prompt, decoder, and processor budget. They are not held-out accuracy measurements. The poster did not yield a completed judgment. The soft generation budget successfully kept that incomplete answer unresolved. At that stage, no OpenAI requests were made and Apple MPS had not been tested. The then-current 46 automated tests passed; those tests use mocked inference and do not download weights.

## v5 context and pass validation

A reported v4 run assessed ten images and returned pass for all ten. Nine contexts were clipped. Explanations confused a filename with a visual description, treated image links as non-functional decoration, and approved a text-bearing timeline without a captured text alternative. See the [audit and regression scope](local-pass-audit.md).

The local context now strips source URLs, source sets, tracking attributes, CSS, scripts, and SVG paths before applying text limits. It retains semantic attributes, captions, and separate naming fields. The exact alt value and its state (missing, empty, filename, generic, or text) are explicit. The enclosing control and its actual captured naming evidence are separate from nearby captions.

Pass validation checks a literal supporting quotation against those text fields. An unnamed link/button cannot pass because its photograph is recognisable or a caption appears outside it. Empty-alt content without captured equivalent text or explicit decorative semantics remains uncertain when the model cannot support its pass. No failed pass is automatically relabeled issue. This conservative policy can increase abstentions on genuinely decorative images whose purpose is not captured. A matching quotation establishes text provenance, not semantic adequacy or full accessible-name computation.

`model_decision` and `model_reason` preserve the parsed model answer. `decision` is the validated result, and `validation_issues` explains any downgrade. The app shows the original model decision and the combined assessment separately. The new prompt/schema/validation version invalidates earlier local cache entries; old responses remain retained. Rerun local checks after updating. Existing weights are reused. Original OpenAI scores and frozen scanner files remain unchanged.

## Compare on the existing external inputs

Prepare the external snapshots if they are not already available. Existing snapshots should be retained unchanged.

```bash
python external_benchmarks.py prepare
# Start with a bounded smoke test, then run the whole ACT subset:
python local_benchmark.py predict --dataset act --limit 1
python local_benchmark.py predict --dataset act
python local_benchmark.py score --dataset act
# Optional longer evaluation:
python local_benchmark.py predict --dataset assets
python local_benchmark.py score --dataset assets
```

No command above makes OpenAI calls. Prediction reads the input snapshot only; scoring reads the reference file separately. Local results go to `evaluation/external-local/<dataset>/local_predictions.json` and `local_report.json`. Original `predictions.json`, `report.json`, and published OpenAI scores are preserved. If model settings change, prediction invalidates cached judgments; scoring rejects stale settings. Runtime failures can be retried by rerunning prediction. Valid uncertain responses, including parse failures, are cached and reported as abstentions.

The report separates raw model judgments (`raw_model`), validated local judgments (`local_only`), and the current disagreement policy (`combined_review_all`) and includes coverage, abstentions, issue recall, parse errors, runtime errors, device, and elapsed time. Unrun cases in a partial run remain unresolved in the metrics. Public benchmark exposure, the restricted ACT subset, and the ASSETS quality-rating proxy still limit interpretation. ASSETS has no passing references in this import and cannot establish false-positive performance.

## Troubleshooting

- Disabled local button: install `requirements-local.txt` in the same environment that launches Streamlit, then restart it.
- Download failure: check network access to Hugging Face and available disk space. No API key fixes a model-download error.
- Memory error: stop the run, close other applications, and retry one image. The app does not silently change device or switch to a cloud service.
- Mostly uncertain results: inspect raw responses and context truncation, then run the separate benchmark. Do not convert malformed text into a pass.
- Want the original API-only implementation: use branch `api-baseline-v1`. Current OpenAI mode uses review-all routing; recorded baseline scores use the original routing.
