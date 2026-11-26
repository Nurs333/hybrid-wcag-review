# Third-party sources

## W3C ACT fixtures

`evaluation/act/inputs/*.html`, `inputs.json`, and `references.json` are selected from the [W3C ACT test catalogue](https://www.w3.org/WAI/content-assets/wcag-act-rules/testcases.json), rule [23a2a8](https://www.w3.org/WAI/standards-guidelines/act/rules/23a2a8/). Two original PNG assets are preserved as base64 text for portable offline rendering; decoding restores identical source bytes. Source URLs and hashes are recorded in the manifest. Fixture titles and author/copyright metadata are preserved in the source HTML.

The catalogue identifies its license at <https://act-rules.github.io/pages/license/>. The full notice is included in [evaluation/act/LICENSE-W3C.md](evaluation/act/LICENSE-W3C.md). Consult it and the linked W3C notices for reuse conditions. These fixtures are attributed regression material; this repository does not claim authorship of them.

## Qwen weights

Optional local inference downloads `Qwen/Qwen3-VL-2B-Instruct` from Hugging Face, revision `89644892e4d85e24eaac8bacfd4f463576704203`. The model card declares Apache-2.0. The weights are not included in this repository and were not trained or fine-tuned for this project. See the upstream model card and license before redistributing them.

## Dependencies

Playwright/Chromium, Streamlit, PyTorch, Transformers, Pydantic, Pillow, LM Format Enforcer, and the optional OpenAI SDK retain their respective licenses. Installing them does not transfer their authorship to this project. The built-in demo uses an original simple SVG illustration and does not reuse the prototype's stock photos.
