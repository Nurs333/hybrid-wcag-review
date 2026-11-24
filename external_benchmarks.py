"""Import external image references without exposing labels to the model.

Downloads and experiment files stay under evaluation/external-local/. Published
summaries contain aggregate counts; source CSVs and images are not vendored.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment
from PIL import Image

import ai_check
from image_rules import apply_rules
from website_checker import extract_html_records, fetch_resource
from web_evaluation import engine_hashes, fingerprint, metrics, read_json, sha256, write_json

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "evaluation" / "external-local"
ACT_INDEX = "https://www.w3.org/WAI/content-assets/wcag-act-rules/testcases.json"
ASSETS_CSV = "https://zenodo.org/records/21359354/files/DB_assets2026_submission.csv?download=1"
ACT_RULES = {"qt1vmo": "Image accessible name is descriptive", "23a2a8": "Image has non-empty accessible name"}
MODEL_FIELDS = set(ai_check.CONTEXT_FIELDS) | {"page", "image_path", "scan_id"}


def download(url, path, limit=12_000_000):
    path = Path(path)
    if not path.exists():
        data, _, _ = fetch_resource(url, limit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path.read_bytes()


def image_capture(url):
    """Cache source bytes and a static PNG. No live-page replacement for missing assets."""
    digest = sha256(url.encode())
    raw = LOCAL / "raw" / "images" / digest
    data = download(url, raw)
    with Image.open(BytesIO(data)) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("animated_image_requires_temporal_review")
        if image.width * image.height > 25_000_000:
            raise ValueError("oversized_image")
        output = LOCAL / "images" / (digest + ".png")
        output.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGBA").save(output)
    return {"image_path": str(output.relative_to(ROOT)), "image_sha256": sha256(output.read_bytes())}


def human_reference(scores):
    """A declared quality-rating proxy, not an author-provided WCAG verdict."""
    if not scores or any(type(score) is not int or score not in range(1, 6) for score in scores):
        raise ValueError("Human original-alt ratings must be integers from 1 to 5.")
    counts = Counter("issue" if s <= 2 else "pass" if s >= 4 else "uncertain" for s in scores)
    decision = "uncertain"
    for label in ("issue", "pass"):
        if counts[label] > len(scores) / 2:
            decision = label
    return {"decision": decision, "ratings": scores, "rating_count": len(scores), "rating_categories": dict(counts)}


def assets_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        # These are the only source columns used: no teacher scores or rewrites.
        key = (row["page_url"], row["image_url"], row["original_alt_text"])
        groups[key].append(row)
    return groups


def assets_context(row):
    def clean(value):
        return "" if value in {None, "", "No textual context found"} else value
    context = clean(row.get("html_context"))
    nearby = " ".join(filter(None, (clean(row.get("immediate_context")), clean(row.get("nearby_context")))))
    # Historical source files are identifiers, not current website URLs.
    # The CSV does not establish the complete original DOM or control semantics.
    return {
        "page": row["page_url"], "alt": row["original_alt_text"],
        "image_html": "", "context_html": context[:24000],
        "nearby_text": nearby[:12000], "context_truncated": len(context) > 24000 or len(nearby) > 12000,
        "capture_method": "external_source_image",
        "scan_id": "external-assets-2026",
    }


def act_context(markup, url):
    soup = BeautifulSoup(markup, "html.parser")
    if soup.find(["script", "style"]) or any("stylesheet" in link.get("rel", []) for link in soup.find_all("link")):
        raise ValueError("styles_or_scripts_require_rendering")
    # Test-page titles/comments can reveal "Passed Example" or "Failed Example".
    if soup.head:
        soup.head.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    if soup.find(["script", "style", "link"]) or len(soup.find_all("img")) != 1:
        raise ValueError("unsupported_markup_or_target_count")
    image = soup.find("img")
    if not image.get("src"):
        raise ValueError("no_source_image")
    if image.get("style"):
        raise ValueError("inline_style_requires_rendering")
    _, records, _ = extract_html_records(str(soup), url, 1)
    record = records[0]
    if record["aria_hidden"]:
        raise ValueError("hidden_state_requires_rendering")
    return {key: value for key, value in record.items() if key in ai_check.CONTEXT_FIELDS} | {
        "page": url, "src": record["src"], "scan_id": "external-act",
    }


def prepare_act():
    raw = download(ACT_INDEX, LOCAL / "raw" / "act-testcases.json")
    catalog = json.loads(raw)
    selected = [entry for entry in catalog["testcases"] if entry["ruleId"] in ACT_RULES]
    cases, references, exclusions = [], {}, []
    for entry in selected:
        key = "act_" + entry["testcaseId"]
        if entry["expected"] == "inapplicable":
            exclusions.append({"case_id": key, "reason": "inapplicable", "rule_id": entry["ruleId"]})
            continue
        try:
            markup = download(entry["url"], LOCAL / "raw" / (entry["testcaseId"] + ".html"), 2_000_000).decode("utf-8")
            case = act_context(markup, entry["url"])
            case.update(image_capture(case["src"]), case_id=key, rule_id=entry["ruleId"])
            cases.append(case)
            references[key] = {"decision": {"passed": "pass", "failed": "issue"}[entry["expected"]], "act_expected": entry["expected"], "rule_id": entry["ruleId"]}
        except Exception as error:
            exclusions.append({"case_id": key, "reason": str(error) if isinstance(error, ValueError) else type(error).__name__, "rule_id": entry["ruleId"]})
    return cases, references, {
        "source": ACT_INDEX, "source_sha256": sha256(raw), "rules": ACT_RULES,
        "selected_rule_cases": len(selected), "excluded": exclusions,
        "label_scope": "Agreement with individual ACT rule references on a restricted source-HTML img subset, not page-level WCAG accuracy. The baseline flags semantic alternatives more broadly than a non-empty-name rule; disagreements require rule-scope interpretation.",
    }


def prepare_assets():
    raw = download(ASSETS_CSV, LOCAL / "raw" / "assets-2026.csv")
    rows = list(csv.DictReader(StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    groups = assets_groups(rows)
    candidates, exclusions = [], []
    for key, ratings in groups.items():
        case_id = "assets_" + fingerprint(key)[:20]
        if urlsplit(key[1]).scheme not in {"https", "http"}:
            exclusions.append({"case_id": case_id, "reason": "relative_image_path_not_recoverable_from_release"})
            continue
        per_reviewer = defaultdict(set)
        for row in ratings:
            per_reviewer[row["user"]].add(int(row["user_assessment"]))
        if any(len(values) != 1 for values in per_reviewer.values()):
            exclusions.append({"case_id": case_id, "reason": "conflicting_duplicate_reviewer_ratings"})
            continue
        reference = human_reference([next(iter(values)) for values in per_reviewer.values()])
        candidates.append((case_id, ratings[0], reference))
    def capture(candidate):
        key, row, reference = candidate
        try:
            case = assets_context(row)
            case.update(image_capture(row["image_url"]), case_id=key, src=row["image_url"])
            return case, reference, None
        except Exception as error:
            return None, None, {"case_id": key, "reason": str(error) if isinstance(error, ValueError) else type(error).__name__}
    cases, references = [], {}
    # Independent downloads are bounded; ordering is retained, not selected by outcomes.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for case, reference, failure in pool.map(capture, candidates):
            if failure:
                exclusions.append(failure)
            else:
                cases.append(case)
                references[case["case_id"]] = reference
    return cases, references, {
        "source": "https://zenodo.org/records/21359354", "source_sha256": sha256(raw),
        "source_rows": len(rows), "unique_image_urls": len({r["image_url"] for r in rows}),
        "unique_page_image_alt_groups": len(groups), "absolute_image_groups": len(candidates),
        "source_page_counts": dict(Counter(case["page"] for case in cases)), "excluded": exclusions,
        "label_scope": "Human quality-rating proxy: 1-2 issue, 3 uncertain, 4-5 pass; a category must have a strict majority across distinct reviewers, otherwise uncertain. This mapping is an operational choice, not a published WCAG pass/fail verdict. Historical DOM context is incomplete; no original pages are reconstructed from filenames.",
        "rating_provenance": "Only user_assessment of the original alt is used. Teacher/model ratings and generated alternatives are excluded. Original study blinding and reviewer expertise are not established by this importer.",
    }


def prepare(name):
    folder = LOCAL / name
    if (folder / "inputs.json").exists():
        raise ValueError(f"{name} inputs already exist; preserve this snapshot or use a fresh checkout.")
    cases, references, provenance = prepare_act() if name == "act" else prepare_assets()
    data = {"dataset": name, "cases": cases, "engine_sha256": engine_hashes(), "importer_sha256": sha256(Path(__file__).read_bytes()), "model": ai_check.DEFAULT_MODEL}
    data["inputs_sha256"] = fingerprint(data)
    write_json(folder / "inputs.json", data)
    refs = {"inputs_sha256": data["inputs_sha256"], "references": references, "provenance": provenance}
    refs["references_sha256"] = fingerprint(refs)
    write_json(folder / "references.json", refs)
    print(name, "prepared:", len(cases), "cases; exclusions:", len(provenance["excluded"]), flush=True)


def validate_inputs(data):
    if data["inputs_sha256"] != fingerprint({k: v for k, v in data.items() if k != "inputs_sha256"}):
        raise ValueError("Inputs changed after import.")
    if data["engine_sha256"] != engine_hashes() or data["importer_sha256"] != sha256(Path(__file__).read_bytes()):
        raise ValueError("The engine or import/mapping policy changed; use a new experiment.")
    for case in data["cases"]:
        if sha256(ai_check.resolve_image_path(case).read_bytes()) != case["image_sha256"]:
            raise ValueError("An imported image changed.")


def model_task(case):
    return {key: value for key, value in case.items() if key in MODEL_FIELDS}


def predict(name, client=None):
    folder = LOCAL / name
    data = read_json(folder / "inputs.json")
    validate_inputs(data)
    if client is None and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY in this terminal before prediction.")
    path = folder / "predictions.json"
    output = read_json(path) if path.exists() else {"inputs_sha256": data["inputs_sha256"], "records": {}}
    if output["inputs_sha256"] != data["inputs_sha256"]:
        raise ValueError("Predictions identify another input snapshot.")
    for case in data["cases"]:
        key = case["case_id"]
        if output["records"].get(key, {}).get("result"):
            continue
        start = time.perf_counter()
        try:
            record = {"result": ai_check.check_image(model_task(case), model=data["model"], client=client)}
        except Exception as error:
            record = {"result": None, "error": type(error).__name__}
        record["elapsed_seconds"] = time.perf_counter() - start
        output["records"][key] = record
        write_json(path, output)
        print(name, key, "saved" if record["result"] else "unresolved API error", flush=True)
    return output


def score(name):
    folder = LOCAL / name
    data, refs = read_json(folder / "inputs.json"), read_json(folder / "references.json")
    validate_inputs(data)
    if refs["references_sha256"] != fingerprint({k: v for k, v in refs.items() if k != "references_sha256"}) or refs["inputs_sha256"] != data["inputs_sha256"]:
        raise ValueError("Reference snapshot changed or mismatches inputs.")
    path = folder / "predictions.json"
    predictions = read_json(path) if path.exists() else None
    if predictions and predictions["inputs_sha256"] != data["inputs_sha256"]:
        raise ValueError("Predictions identify another input snapshot.")
    ids = {case["case_id"] for case in data["cases"]}
    if set(refs["references"]) != ids:
        raise ValueError("References must align exactly to input cases.")
    records = predictions["records"] if predictions else {}
    rules, ai, hybrid, details = [], [], [], []
    for case in data["cases"]:
        key = case["case_id"]
        reference = refs["references"][key]
        expected = reference["decision"]
        rule = apply_rules(dict(case))
        rule_decision = "issue" if rule["rule_result"] == "potential_issue" else "uncertain"
        automated = (records.get(key, {}).get("result") or {}).get("decision", "uncertain")
        combined = "issue" if rule_decision == "issue" else automated
        rules.append((expected, rule_decision))
        ai.append((expected, automated))
        hybrid.append((expected, combined))
        details.append({"case_id": key, "rule_id": case.get("rule_id"), "reference": expected, "rules": rule_decision, "ai": automated if key in records else "not_run", "hybrid": combined, "rule_flags": rule["rule_flags"]})
    complete = bool(ids) and set(records) == ids and all(record.get("result") for record in records.values())
    by_rule = {}
    if name == "act":
        for rule_id in sorted(ACT_RULES):
            subset = [row for row in details if row["rule_id"] == rule_id]
            by_rule[rule_id] = {"cases": len(subset), "rules": metrics([(row["reference"], row["rules"]) for row in subset])}
    successes = [record for record in records.values() if record.get("result")]
    report = {
        "dataset": name, "inputs_sha256": data["inputs_sha256"], "references_sha256": refs["references_sha256"],
        "rules_by_act_rule": by_rule,
        "prepared_cases": len(ids), "reference_counts": dict(Counter(r["decision"] for r in refs["references"].values())),
        "provenance": refs["provenance"], "rules": metrics(rules),
        "ai_status": "complete" if complete else "partial" if records else "not_run",
        "ai": metrics(ai) if records else None, "hybrid": metrics(hybrid) if records else None,
        "successful_ai_results": sum(bool(record.get("result")) for record in records.values()),
        "api_errors": sum(bool(record.get("error")) for record in records.values()),
        "resources": {
            "successful_input_tokens": sum((record["result"].get("usage") or {}).get("input_tokens", 0) or 0 for record in successes),
            "successful_output_tokens": sum((record["result"].get("usage") or {}).get("output_tokens", 0) or 0 for record in successes),
            "successful_elapsed_seconds": sum(record["elapsed_seconds"] for record in successes),
            "note": "Successful calls only; failed-call usage, retry history, dollar billing, and independent hybrid latency are not measured.",
        },
        "details": details,
        "interpretation": "Rule silence is uncertain, not pass. Unknown reference ratings are excluded from binary metrics and counted separately. No model score is reported before model requests. Public benchmark exposure means these are external regression tests, not proof of unseen-model generalization.",
    }
    write_json(folder / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "predict", "score"))
    parser.add_argument("--dataset", choices=("all", "act", "assets"), default="all")
    parser.add_argument("--allow-api", action="store_true", help="Permit paid requests for every prepared case.")
    args = parser.parse_args()
    names = ("act", "assets") if args.dataset == "all" else (args.dataset,)
    if args.command == "predict" and not args.allow_api:
        parser.error("Prediction uses paid OpenAI calls. Add --allow-api to proceed.")
    for name in names:
        if args.command == "prepare":
            prepare(name)
        elif args.command == "predict":
            predict(name)
        else:
            report = score(name)
            print(name, json.dumps({k: report[k] for k in ("prepared_cases", "reference_counts", "rules", "ai_status")}))


if __name__ == "__main__":
    main()
