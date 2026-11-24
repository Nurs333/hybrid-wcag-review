from pathlib import Path
import json

from ai_check import assessment_key, check_image


def main():
    folder = Path(__file__).resolve().parent
    tasks = json.loads(
        (folder / "ai_tasks.json").read_text(encoding="utf-8")
    )
    results_path = folder / "ai_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []
    by_page = {result["page"]: result for result in results}

    for task in tasks:
        cached = by_page.get(task["page"])
        if cached and cached.get("assessment_key") == assessment_key(task):
            continue
        print("Checking:", task["page"])
        output = check_image(task)
        by_page[task["page"]] = output
        results = [by_page[item["page"]] for item in tasks if item["page"] in by_page]
        temporary = results_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(results_path)
        print("Saved:", output["page"], output["decision"])

    print("Total AI results:", sum(task["page"] in by_page for task in tasks))


if __name__ == "__main__":
    main()
