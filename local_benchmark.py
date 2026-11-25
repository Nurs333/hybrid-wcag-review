"""Evaluate local inference on existing external snapshots without OpenAI calls.

Prediction reads inputs only. Scoring reads references in a separate step.
Original OpenAI predictions and reports are never overwritten.
"""

import argparse
from collections import Counter
from pathlib import Path

import external_benchmarks as external
import local_model
from image_rules import apply_rules
from review_pipeline import POLICY_VERSION, combine
from web_evaluation import fingerprint, metrics, read_json, write_json


def predict(name, limit=None):
    folder = external.LOCAL / name
    data = read_json(folder / "inputs.json")
    external.validate_inputs(data)
    path = folder / "local_predictions.json"
    output = read_json(path) if path.exists() else {"inputs_sha256": data["inputs_sha256"], "records": {}}
    if output["inputs_sha256"] != data["inputs_sha256"]:
        raise ValueError("Local predictions identify another input snapshot.")
    cases = data["cases"] if limit is None else data["cases"][:limit]
    for case in cases:
        case_id = case["case_id"]
        task = external.model_task(case)
        key = local_model.assessment_key(task)
        previous = output["records"].get(case_id, {}).get("result") or {}
        if previous.get("assessment_key") == key:
            continue
        try:
            record = {"result": local_model.check_image(task)}
        except Exception as error:
            record = {"result": None, "error": type(error).__name__}
        output["records"][case_id] = record
        write_json(path, output)
        print(name, case_id, (record["result"] or {}).get("decision", "runtime_error"), flush=True)
    return output


def score(name):
    folder = external.LOCAL / name
    data, refs = read_json(folder / "inputs.json"), read_json(folder / "references.json")
    external.validate_inputs(data)
    if refs["references_sha256"] != fingerprint({k: v for k, v in refs.items() if k != "references_sha256"}) or refs["inputs_sha256"] != data["inputs_sha256"]:
        raise ValueError("Reference snapshot changed or mismatches inputs.")
    ids = {case["case_id"] for case in data["cases"]}
    if set(refs["references"]) != ids:
        raise ValueError("References must align exactly to input cases.")
    path = folder / "local_predictions.json"
    predictions = read_json(path) if path.exists() else None
    if predictions and (predictions["inputs_sha256"] != data["inputs_sha256"] or not set(predictions["records"]).issubset(ids)):
        raise ValueError("Local predictions do not match this input snapshot.")
    records = predictions["records"] if predictions else {}
    raw_pairs, pairs, combined_pairs, details, results = [], [], [], [], []
    for case in data["cases"]:
        case_id = case["case_id"]
        result = records.get(case_id, {}).get("result")
        if result and result["assessment_key"] != local_model.assessment_key(external.model_task(case)):
            raise ValueError("Local model settings changed. Run local prediction again before scoring.")
        rule = apply_rules(dict(case))
        if result:
            combine(rule, result)
            results.append(result)
        # Missing or failed inference is unresolved even when rules flag a candidate.
        decision = result["decision"] if result else "uncertain"
        raw_decision = result.get("model_decision", decision) if result else "uncertain"
        combined = rule["decision"] if result else "uncertain"
        expected = refs["references"][case_id]["decision"]
        pairs.append((expected, decision))
        raw_pairs.append((expected, raw_decision))
        combined_pairs.append((expected, combined))
        details.append({"case_id": case_id, "reference": expected, "raw_model": raw_decision if result else "not_run", "local": decision if result else "not_run", "combined": combined, "disagreement": bool(rule.get("disagreement")), "validation_issues": result.get("validation_issues", []) if result else [], "parse_error": result.get("parse_error") if result else None})
    report = {
        "dataset": name, "inputs_sha256": data["inputs_sha256"], "references_sha256": refs["references_sha256"],
        "provider": "local", "model": local_model.MODEL_ID, "model_revision": local_model.MODEL_REVISION,
        "prompt_version": local_model.PROMPT_VERSION, "routing_policy": POLICY_VERSION,
        "validation_policy": local_model.local_evidence.VERSION,
        "status": "complete" if len(results) == len(ids) else "partial" if records else "not_run",
        "prepared_cases": len(ids), "successful_inference": len(results),
        "parse_errors": sum(bool(result.get("parse_error")) for result in results),
        "runtime_errors": sum(bool(record.get("error")) for record in records.values()),
        "devices": dict(Counter(result["device"] for result in results)),
        "local_only": metrics(pairs) if records else None,
        "raw_model": metrics(raw_pairs) if records else None,
        "passes_requiring_review": sum(bool(result.get("validation_issues")) for result in results),
        "combined_review_all": metrics(combined_pairs) if records else None,
        "elapsed_seconds": sum(result["elapsed_seconds"] for result in results),
        "details": details,
        "interpretation": "Restricted public regression subset, not unseen-model generalization or page WCAG conformance. Abstentions reduce coverage and issue recall. Elapsed time includes cold loading for the first request; no dollar or energy cost is measured. Historic OpenAI results belong to a different backend and routing policy.",
    }
    write_json(folder / "local_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("predict", "score"))
    parser.add_argument("--dataset", choices=("act", "assets"), default="act")
    parser.add_argument("--limit", type=int, help="Smoke-test only the first N inputs; a partial score still counts unrun cases as unresolved.")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.command == "predict":
        predict(args.dataset, args.limit)
    else:
        import json
        print(json.dumps(score(args.dataset), indent=2))


if __name__ == "__main__":
    main()
