from pathlib import Path
import json

folder = Path(__file__).parent

answers = json.loads(
    (folder / "answer_key.json").read_text(encoding="utf-8")
)

observations = json.loads(
    (folder / "observations.json").read_text(encoding="utf-8")
)

ai_results = json.loads(
    (folder / "ai_results_holdout.json").read_text(encoding="utf-8")
)

targets = {
    record["page"]: record
    for record in observations
    if record["image_id"] == "target"
}

ai_by_page = {
    result["page"]: result
    for result in ai_results
}

correct_issues = 0
false_alarms = 0
missed_issues = 0
correct_passes = 0
uncertain = 0
evaluated = 0

for answer in answers:
    if answer["split"] != "holdout":
        continue

    page = Path(answer["file"]).name
    expected = answer["expected_label"]
    record = targets[page]

    if record["rule_result"] == "potential_issue":
        decision = "issue"
        source = "rules"
    else:
        result = ai_by_page[page]
        decision = result["decision"]
        source = "AI"

    evaluated += 1
    print(page, "| expected:", expected,
          "| decision:", decision, "| source:", source)

    if decision == "uncertain":
        uncertain += 1
    elif decision == "issue":
        if expected == "issue":
            correct_issues += 1
        else:
            false_alarms += 1
            print("FALSE ALARM:", page)
            print("Reference reason:", answer["rationale"])

            if source == "AI":
                print("AI reason:", ai_by_page[page]["reason"])
                print("AI evidence:", ai_by_page[page]["evidence"])

            print()
    elif decision == "pass":
        if expected == "issue":
            missed_issues += 1
        else:
            correct_passes += 1
    else:
        raise ValueError(f"Unexpected decision for {page}: {decision}")

print()
print("Cases evaluated:", evaluated)
print("Correctly identified issues:", correct_issues)
print("False alarms:", false_alarms)
print("Missed issues:", missed_issues)
print("Correct passes:", correct_passes)
print("Uncertain — human review needed:", uncertain)