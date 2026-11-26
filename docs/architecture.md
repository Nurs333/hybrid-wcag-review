# Architecture and boundaries

## Browser evidence

`capture.scan` opens Chromium and inventories supported top-level image elements. Inventory and visual capture are separate budgets. Each record pairs a DOM snapshot with the exact node's `backendDOMNodeId` and `Accessibility.getPartialAXTree` result. It records name sources and ignored reasons rather than reimplementing accessible-name computation in Python.

The image and enclosing control have separate checks. An empty-alt image can be absent from the accessibility tree while its parent link remains exposed and unnamed. Conversely, text inside that link or CSS-generated text can give the link a name. A sibling caption does not necessarily do so.

`facts.assess` only creates findings for exposed relevant nodes with empty computed names. Missing browser evidence is unknown. Presentation or hidden treatment does not automatically establish that the content is decorative; the UI requests contextual review. Generic and filename alts prompt review, not definitive findings.

Before a screenshot, the scanner refreshes the node's DOM and name evidence. After capture it checks that source, alt, and control identity remain stable; changes invalidate that capture. Dynamic pages can still change other properties or occlude an image. Partial crops and errors remain visible in the record.

## Optional visual notes

`vision.observe` deliberately has a path-and-provider interface. It does not accept an alt, HTML, expected label, or structural verdict. This reduces opportunities for a small model to rationalize a supplied description or contradict known DOM facts. It does not eliminate visual hallucinations.

The same literal observation schema is used for local and paid providers. Local JSON generation is constrained with LM Format Enforcer and validated with Pydantic. The cache is keyed by pixel hash, provider/model/revision, prompt, schema, pixel budget, and decoding settings. Failed requests are not cached. Provider changes do not silently reuse another provider's notes.

The model cannot clear a finding or set `content_review` to passed. A reviewer can optionally record a separate issue/pass/uncertain decision, with a timestamp. The default content state is not reviewed, even for plausible non-empty alternatives.

## Persistence and exports

Every scan uses a fresh UUID under `runs/v2/`. Captures are relative filenames; scan identifiers and capture filenames are constrained before filesystem access. Checkpoints are written by atomic rename. Exports escape website text and HTML. Model outputs and reviewer decisions stay separate from browser evidence.

The local Streamlit UI performs scans in a worker thread because Playwright's synchronous API cannot run inside an active event loop. The command-line interface uses the same capture and reporting code.

## Scope of trust

The URL guard rejects credentials and non-public resolved addresses. Browser requests to previously unseen hosts are checked as well. This is useful local protection, not a complete sandbox for hostile websites: DNS rebinding, browser network features, browser exploits, and resource exhaustion are not comprehensively addressed. A deployed service would need isolated workers, egress controls, quotas, and a separate threat model.

Source HTML and image pixels are untrusted evidence. They are not executed inside exported reports. Local and API models can still be influenced by text in images; their descriptions are always marked unverified.
