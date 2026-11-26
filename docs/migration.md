# Move from the prototype

The old implementation is preserved on the `prototype-v5` Git branch. This rewrite does not erase any local captures, SQLite files, or model downloads. It reads only version-two scans under `runs/v2/`; legacy JSON results are intentionally not treated as current evidence.

Download the new repository into a **fresh folder** rather than merging its ZIP into an old environment. Python 3.11/3.12 is recommended. If you use Conda:

```bash
conda create -n altreview python=3.12
conda activate altreview
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m streamlit run app.py
```

The default app does not require PyTorch or an API key. `review_app.py` remains a compatible launcher. Install the separate local or paid requirements only if you want optional descriptions.

Changes you will see:

- Names are read from Chromium, rather than guessed from a few HTML attributes.
- All supported elements in the bounded inventory receive a name check; the screenshot limit does not discard the rest.
- A green name-present result is an atomic check. The UI no longer labels the entire image or page as passed.
- A local model describes pixels only. It does not decide whether an alternative is adequate or overrule browser evidence.
- No reviewer ID or mandatory labeling session. A personal decision is optional.
- Exported HTML includes capture images and evidence. JSON retains detailed provenance.

Existing API keys in another terminal are not inherited by a newly opened terminal. A key is only needed for the optional paid provider. Do not put credentials into source files or commit them.
