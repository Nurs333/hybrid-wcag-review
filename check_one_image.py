from pathlib import Path
import json

from ai_check import check_image


if __name__ == "__main__":
    folder = Path(__file__).resolve().parent
    tasks = json.loads((folder / "ai_tasks.json").read_text(encoding="utf-8"))
    output = check_image(tasks[0])
    (folder / "ai_result_one.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(output, indent=2, ensure_ascii=False))
