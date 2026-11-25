"""Review-all v2 routing with separate model caches and explicit disagreements.

The frozen website_checker.py remains available for reproducing baseline-v1.
"""

import argparse
import os

import ai_check
import local_model
from image_rules import apply_rules
from web_evaluation import fingerprint
from website_checker import save_run, scan_in_worker

POLICY_VERSION = "review-all-v2"


def pending_ai_records(run):
    """Eligible images include rule flags; hidden/unavailable evidence stays skipped."""
    return [record for record in run["images"] if record.get("capture_status") == "captured" and record.get("visible") is not False and record.get("image_path") and "image_html" in record]


def assessment_key(record, provider="local", model=None):
    if provider == "local":
        return local_model.assessment_key(record)
    if provider == "openai":
        return ai_check.assessment_key(record, model or ai_check.DEFAULT_MODEL)
    raise ValueError("Choose local or openai.")


def remember_result(record):
    previous = record.get("ai_result")
    if previous and previous.get("assessment_key"):
        provider = previous.get("provider", "openai")
        record.setdefault("model_results", {})[provider + ":" + previous["assessment_key"]] = previous


def combine(record, result):
    flagged = record.get("rule_result") == "potential_issue"
    disagreement = flagged and result["decision"] == "pass"
    record.update(
        ai_result=result, decision="uncertain" if disagreement else result["decision"],
        source="Local model" if result.get("provider") == "local" else "OpenAI",
        disagreement=disagreement, needs_human_review=disagreement or result["decision"] == "uncertain",
        review_policy=POLICY_VERSION,
        review_reason="Rules flagged a potential issue but the model returned pass. Human review is needed." if disagreement else result["reason"],
    )


def select_backend(run, provider="local", model=None):
    if provider not in {"local", "openai"}:
        raise ValueError("Choose local or openai.")
    run.update(review_policy=POLICY_VERSION, active_provider=provider)
    for record in pending_ai_records(run):
        remember_result(record)
        apply_rules(record)
        try:
            key = assessment_key(record, provider, model)
        except OSError:
            key = None
        result = record.get("model_results", {}).get(provider + ":" + str(key))
        if result:
            combine(record, result)
        else:
            record.pop("ai_result", None)
            same_error = record.get("ai_error") and record.get("ai_error_provider") == provider and record.get("ai_error_key") == key
            if not same_error:
                record.pop("ai_error", None)
            record.update(
                decision="needs_review" if same_error else "potential_issue" if record["rule_result"] == "potential_issue" else "needs_review",
                source=("Local error" if provider == "local" else "OpenAI error") if same_error else "rules" if record["rule_result"] == "potential_issue" else "pending",
                disagreement=False, needs_human_review=True,
                review_reason=record["rule_reason"], review_policy=POLICY_VERSION,
            )
    return run


def review_assessment_id(record):
    result = record.get("ai_result") or {}
    return fingerprint({"policy": POLICY_VERSION, "provider": result.get("provider", "openai") if result else None, "assessment_key": result.get("assessment_key"), "response_id": result.get("response_id"), "rule_flags": record.get("rule_flags", []), "decision": record["decision"]})


def run_ai(run, provider="local", model=None, progress=None, client=None):
    if provider == "openai" and client is None and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY before explicitly choosing OpenAI.")
    select_backend(run, provider, model)
    records = pending_ai_records(run)
    for index, record in enumerate(records, 1):
        key = None
        try:
            key = assessment_key(record, provider, model)
            cached = record.get("model_results", {}).get(provider + ":" + key)
            if cached is None:
                if provider == "local":
                    result = local_model.check_image(record)
                else:
                    result = ai_check.check_image(record, model=model or ai_check.DEFAULT_MODEL, client=client)
                    result["provider"] = "openai"
                record.setdefault("model_results", {})[provider + ":" + key] = result
            else:
                result = cached
            combine(record, result)
            record.pop("ai_error", None)
            record.pop("ai_error_provider", None)
            record.pop("ai_error_key", None)
        except Exception as error:
            record.pop("ai_result", None)
            record.update(decision="needs_review", source="Local error" if provider == "local" else "OpenAI error", ai_error=str(error)[:300], ai_error_provider=provider, ai_error_key=key, needs_human_review=True)
        save_run(run)
        if progress:
            progress(index, len(records))
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--provider", choices=("local", "openai"), default="local")
    parser.add_argument("--mode", choices=("browser", "html"), default="browser")
    parser.add_argument("--max-images", type=int, default=12)
    parser.add_argument("--assess", action="store_true")
    args = parser.parse_args()
    run = scan_in_worker(args.url, args.max_images, args.mode)
    if args.assess:
        run_ai(run, provider=args.provider)
    for record in run["images"]:
        print(record["image_key"], record["decision"], "disagreement" if record.get("disagreement") else "")
    print("Saved scan:", run["run_path"])


if __name__ == "__main__":
    main()
