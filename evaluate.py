from pathlib import Path
import json

folder = Path(__file__).parent

observations = json.loads(
    (folder / "observations.json").read_text(encoding="utf-8")
)

answer_key = json.loads(
    (folder / "answer_key.json").read_text(encoding="utf-8")
)

targets = {}

for record in observations:
    if record["image_id"] == "target":
        targets[record["page"]] = record

correct_flags = 0
false_flags = 0
issues_awaiting_review = 0
evaluated = 0

for answer in answer_key:
    if answer["split"] != "development":
        continue

    page = Path(answer["file"]).name
    record = targets[page]

    expected = answer["expected_label"]
    flagged = record["rule_result"] == "potential_issue"

    evaluated += 1

    if flagged:
        if expected == "issue":
            correct_flags += 1
            print(page, "— correctly flagged")
        else:
            false_flags += 1
            print(page, "— false alarm")

    elif expected == "issue":
        issues_awaiting_review += 1
        print(page, "— issue still awaiting review")
        print("  Category:", answer["category"])
        print("  Reason:", answer["rationale"])

print()
print("Cases evaluated:", evaluated)
print("Correct flags:", correct_flags)
print("False alarms:", false_flags)
print("Issues awaiting review:", issues_awaiting_review)