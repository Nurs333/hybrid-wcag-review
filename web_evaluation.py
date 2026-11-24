"""Freeze, collect, predict, and score a public-image evaluation.

Collection and prediction never read reference labels. All local experiment data
lives under evaluation/local/, which is excluded from version control.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit

from PIL import Image

import ai_check
from image_rules import apply_rules
from website_checker import scan_in_worker

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "evaluation" / "local"
FROZEN_FILES = ("ai_check.py", "image_rules.py", "website_checker.py")
DECISIONS = {"pass", "issue", "uncertain"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def engine_hashes():
    return {name: sha256((ROOT / name).read_bytes()) for name in FROZEN_FILES}


def validate_lock(lock, model=None):
    if lock["engine_sha256"] != engine_hashes():
        raise ValueError("The frozen scanner, prompt, or rules changed. Start a new experiment.")
    if lock["sources_sha256"] != sha256((ROOT / "evaluation" / "sources.json").read_bytes()):
        raise ValueError("The frozen source plan changed. Start a new experiment.")
    if model is not None and lock["model"] != model:
        raise ValueError("The model differs from the frozen model.")


def freeze(model):
    path = LOCAL / "protocol-lock.json"
    if path.exists():
        validate_lock(read_json(path), model)
        return read_json(path)
    lock = {
        "baseline_commit": "70eb6b1a5c051d61e682cd8bd4e91f5e71e2b28e",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "engine_sha256": engine_hashes(),
        "sources_sha256": sha256((ROOT / "evaluation" / "sources.json").read_bytes()),
        "prompt_sha256": sha256(ai_check.INSTRUCTIONS.encode()),
        "sampling": read_json(ROOT / "evaluation" / "sources.json"),
    }
    write_json(path, lock)
    return lock


def dataset_digest(dataset):
    return fingerprint({key: value for key, value in dataset.items() if key != "dataset_sha256"})


def validate_dataset(dataset):
    if dataset.get("dataset_sha256") != dataset_digest(dataset):
        raise ValueError("Dataset contents changed after collection.")
    validate_lock(dataset["protocol"])
    for case in dataset["cases"]:
        if sha256(ai_check.resolve_image_path(case).read_bytes()) != case["image_sha256"]:
            raise ValueError(f'Captured image changed: {case["case_id"]}')


def collect(mode):
    destination = LOCAL / "dataset.json"
    if destination.exists():
        raise ValueError("A dataset already exists. Preserve it; use a new checkout for a new experiment.")
    lock = freeze(ai_check.DEFAULT_MODEL)
    plan = lock["sampling"]
    cases, log, seen, hosts = [], [], set(), Counter()
    # A failed collection can be resumed without refetching completed source scans.
    checkpoint = LOCAL / "capture-checkpoints.json"
    captures = read_json(checkpoint) if checkpoint.exists() else {"mode": mode, "runs": {}}
    if captures["mode"] != mode:
        raise ValueError("Resume with the same capture mode.")
    for source in plan["sources"]:
        if len(cases) >= plan["target_images"]:
            break
        url = source["url"]
        print("Capturing:", url, flush=True)
        try:
            if url not in captures["runs"]:
                captures["runs"][url] = scan_in_worker(url, plan["scan_limit"], mode)
                write_json(checkpoint, captures)
            run = captures["runs"][url]
        except Exception as error:
            log.append({"url": url, "status": "capture_failed", "error": type(error).__name__})
            continue
        host = urlsplit(run["url"]).hostname
        selected, excluded = [], []
        for record in run["images"]:
            if len(cases) >= plan["target_images"] or hosts[host] >= plan["images_per_site"]:
                break
            reason = None
            path = None
            if record.get("capture_status") != "captured" or record.get("visible") is False:
                reason = "not_captured_or_not_visible"
            else:
                path = ai_check.resolve_image_path(record)
                with Image.open(path) as image:
                    if min(image.size) < 40:
                        reason = "small_image"
            digest = sha256(path.read_bytes()) if path else None
            if digest in seen:
                reason = "duplicate_bytes"
            if reason:
                excluded.append({"image_key": record["image_key"], "reason": reason})
                continue
            case_id = f"web_{len(cases) + 1:03d}"
            output = LOCAL / "images" / (case_id + path.suffix)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
            # Explicit context allowlist keeps scan predictions out of the dataset.
            case = {key: record.get(key) for key in ai_check.CONTEXT_FIELDS}
            case.update(
                case_id=case_id, page=run["url"], src=record.get("src"),
                image_path=str(output.relative_to(ROOT)), image_sha256=digest,
                capture_mode=mode, source_category=source["category"],
                captured_at=run["created_at"], scan_id=run["scan_id"],
            )
            cases.append(case)
            seen.add(digest)
            hosts[host] += 1
            selected.append(case_id)
        log.append({"url": url, "final_url": run["url"], "status": "captured", "selected": selected, "excluded": excluded})
    write_json(LOCAL / "collection-log.json", log)
    if not cases:
        raise ValueError("No eligible images were captured. Check the capture log or try browser mode.")
    dataset = {
        "protocol": lock, "capture_mode": mode, "cases": cases, "collection_log": log,
        "target_count": plan["target_images"], "actual_count": len(cases),
        "target_met": len(cases) == plan["target_images"],
        "note": "A convenience sample, not a random sample. HTML mode is a source-only pilot; rendered visibility is unverified.",
    }
    dataset["dataset_sha256"] = dataset_digest(dataset)
    write_json(destination, dataset)
    print(f"Saved {len(cases)} cases across {len(hosts)} hostnames. No AI calls or reference labels were used.")


def rules_decision(case):
    record = apply_rules(dict(case))
    return "issue" if record["rule_result"] == "potential_issue" else "uncertain"


def predict(dataset, output_path, model, client=None):
    validate_dataset(dataset)
    validate_lock(dataset["protocol"], model)
    if client is None and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY before running predictions.")
    output_path = Path(output_path)
    if output_path.exists():
        output = read_json(output_path)
        if output["dataset_sha256"] != dataset["dataset_sha256"] or output["model"] != model:
            raise ValueError("Existing predictions belong to a different dataset or model.")
    else:
        output = {"dataset_sha256": dataset["dataset_sha256"], "model": model, "records": {}}
    for case in dataset["cases"]:
        key = case["case_id"]
        previous = output["records"].get(key)
        if previous and previous.get("ai") and not previous.get("error"):
            continue
        start = time.perf_counter()
        result = {"rules": rules_decision(case), "attempted_at": datetime.now(timezone.utc).isoformat()}
        try:
            ai = ai_check.check_image(case, model=model, client=client)
            result.update(ai=ai, hybrid="issue" if result["rules"] == "issue" else ai["decision"])
        except Exception as error:
            result.update(ai=None, hybrid="issue" if result["rules"] == "issue" else "uncertain", error=type(error).__name__)
        result["elapsed_seconds"] = time.perf_counter() - start
        output["records"][key] = result
        write_json(output_path, output)
        print(key, "recorded" if not result.get("error") else "API error; retry available", flush=True)
    return output


def metrics(pairs):
    counts = Counter()
    for expected, decision in pairs:
        if expected not in DECISIONS or decision not in DECISIONS:
            raise ValueError("Unexpected label or prediction.")
        if expected == "uncertain":
            counts["reference_uncertain"] += 1
            continue
        counts["labeled"] += 1
        if decision == "uncertain":
            counts["abstained"] += 1
            counts["abstained_issue" if expected == "issue" else "abstained_pass"] += 1
        else:
            counts["decided"] += 1
            counts[{("issue", "issue"): "tp", ("pass", "issue"): "fp", ("issue", "pass"): "fn", ("pass", "pass"): "tn"}[(expected, decision)]] += 1
    def ratio(a, b):
        return a / b if b else None
    result = {k: counts[k] for k in ("labeled", "decided", "abstained", "abstained_issue", "abstained_pass", "reference_uncertain", "tp", "fp", "fn", "tn")}
    result.update(
        precision=ratio(counts["tp"], counts["tp"] + counts["fp"]),
        recall=ratio(counts["tp"], counts["tp"] + counts["fn"] + counts["abstained_issue"]),
        coverage=ratio(counts["decided"], counts["labeled"]),
        selective_accuracy=ratio(counts["tp"] + counts["tn"], counts["decided"]),
        correct_fraction_all_labeled=ratio(counts["tp"] + counts["tn"], counts["labeled"]),
    )
    return result


def score(dataset, predictions, labels):
    validate_dataset(dataset)
    if predictions["dataset_sha256"] != dataset["dataset_sha256"] or labels["dataset_sha256"] != dataset["dataset_sha256"]:
        raise ValueError("Dataset, predictions, and labels must identify the same capture.")
    validate_lock(dataset["protocol"], predictions["model"])
    if not labels.get("sealed_at"):
        raise ValueError("Complete and seal reference labels before scoring.")
    sealed = {key: value for key, value in labels.items() if key != "labels_sha256"}
    if labels.get("labels_sha256") != fingerprint(sealed):
        raise ValueError("Reference labels changed after sealing.")
    timestamps = [record.get("attempted_at") for record in predictions["records"].values()]
    blind_order = bool(timestamps) and all(t and labels["sealed_at"] <= t for t in timestamps)
    ids = {case["case_id"] for case in dataset["cases"]}
    if set(labels["labels"]) != ids or set(predictions["records"]) != ids:
        raise ValueError("Every dataset case needs a saved reference and an attempted prediction; extra IDs are rejected.")
    results = {}
    for strategy in ("rules", "ai", "hybrid"):
        pairs = []
        for key in sorted(ids):
            record = predictions["records"][key]
            decision = (record.get("ai") or {}).get("decision", "uncertain") if strategy == "ai" else record[strategy]
            pairs.append((labels["labels"][key]["decision"], decision))
        results[strategy] = metrics(pairs)
    records = predictions["records"]
    routed = [r for r in records.values() if r["rules"] != "issue"]
    def usage_total(rows, field):
        return sum(((r.get("ai") or {}).get("usage") or {}).get(field, 0) or 0 for r in rows)
    failures = []
    for case in dataset["cases"]:
        key = case["case_id"]
        record = records[key]
        expected = labels["labels"][key]["decision"]
        if record.get("error") or expected == "uncertain" or record["hybrid"] == "uncertain" or expected != record["hybrid"]:
            failures.append({"case_id": key, "reference": expected, "hybrid": record["hybrid"], "api_error": record.get("error"), "reference_note": labels["labels"][key].get("note", ""), "ai_reason": (record.get("ai") or {}).get("reason", "")})
    return {
        "dataset_sha256": dataset["dataset_sha256"], "capture_mode": dataset["capture_mode"],
        "review_metadata": {k: v for k, v in labels.items() if k != "labels"},
        "references_sealed_before_recorded_predictions": blind_order,
        "independent_review_claim_supported": blind_order and labels.get("relationship") == "External reviewer" and labels.get("automated_decisions_seen") is False,
        "review_order_note": "Local timestamps and reviewer self-report document the workflow; they are not tamper-proof evidence of blinding.",
        "reference_counts": dict(Counter(value["decision"] for value in labels["labels"].values())),
        "cases_by_hostname": dict(Counter(urlsplit(case["page"]).hostname for case in dataset["cases"])),
        "returned_model_counts": dict(Counter((record.get("ai") or {}).get("model", "unavailable") for record in records.values())),
        "strategies": results, "api_errors": sum(bool(r.get("error")) for r in records.values()),
        "recorded_successful_ai_requests": sum(bool(r.get("ai")) for r in records.values()),
        "all_ai_input_tokens": usage_total(records.values(), "input_tokens"),
        "all_ai_output_tokens": usage_total(records.values(), "output_tokens"),
        "hybrid_routed_cases": len(routed),
        "hybrid_routed_input_tokens": usage_total(routed, "input_tokens"),
        "hybrid_routed_output_tokens": usage_total(routed, "output_tokens"),
        "successful_ai_elapsed_seconds": sum(r["elapsed_seconds"] for r in records.values() if r.get("ai")),
        "resource_note": "All images are assessed once for AI-only comparison. Hybrid routed usage is a counterfactual subset of those same calls, not separately measured billing or end-to-end latency. Retry history and failed-request usage are not included. Dollar cost is not inferred from tokens.",
        "failure_review": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    capture = sub.add_parser("collect")
    capture.add_argument("--mode", choices=("browser", "html"), default="browser")
    model = sub.add_parser("predict")
    model.add_argument("--allow-api", action="store_true", help="Explicitly enable paid image requests for all collected cases.")
    evaluation = sub.add_parser("score")
    evaluation.add_argument("--labels", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(ai_check.DEFAULT_MODEL)
        print("Protocol locked. Baseline branch: baseline-v1")
    elif args.command == "collect":
        collect(args.mode)
    elif args.command == "predict":
        if not args.allow_api:
            parser.error("Prediction calls OpenAI on all dataset images. Add --allow-api to run.")
        dataset = read_json(LOCAL / "dataset.json")
        predict(dataset, LOCAL / "predictions.json", dataset["protocol"]["model"])
    else:
        result = score(read_json(LOCAL / "dataset.json"), read_json(LOCAL / "predictions.json"), read_json(args.labels))
        write_json(LOCAL / "comparison.json", result)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
