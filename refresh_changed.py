from pathlib import Path
import json

folder = Path(__file__).parent
results_path = folder / "ai_results.json"

results = json.loads(
    results_path.read_text(encoding="utf-8")
)

changed_pages = {
    "case_02.html",
    "case_10.html",
    "case_24.html",
    "case_28.html"
}

updated_results = [
    result for result in results
    if result["page"] not in changed_pages
]

results_path.write_text(
    json.dumps(updated_results, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("Cached results removed:", len(results) - len(updated_results))
print("Cached results retained:", len(updated_results))