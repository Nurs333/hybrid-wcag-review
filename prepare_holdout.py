from pathlib import Path
import json

folder = Path(__file__).parent

observations = json.loads(
    (folder / "observations.json").read_text(encoding="utf-8")
)

answer_key = json.loads(
    (folder / "answer_key.json").read_text(encoding="utf-8")
)

development_pages = set()

for answer in answer_key:
    if answer["split"] == "holdout":
        development_pages.add(Path(answer["file"]).name)

tasks = []

for record in observations:
    if record["page"] not in development_pages:
        continue

    if record["image_id"] != "target":
        continue

    if record["rule_result"] != "needs_review":
        continue

    task = {
        "page": record["page"],
        "image_path": record["image_path"],
        "alt": record["alt"],
        "image_html": record["image_html"],
        "context_html": record["context_html"],
        "control_type": record["control_type"],
        "control_text": record["control_text"],
        "control_aria_label": record["control_aria_label"]
    }

    tasks.append(task)

output_path = folder / "ai_tasks_holdout.json"

output_path.write_text(
    json.dumps(tasks, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("AI tasks prepared:", len(tasks))