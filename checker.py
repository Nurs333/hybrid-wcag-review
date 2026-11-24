from pathlib import Path
from bs4 import BeautifulSoup
import json

from image_rules import apply_rules

records = []

examples_dir = Path(__file__).parent / "examples"
page_paths = sorted(examples_dir.glob("case_*.html"))

for page_path in page_paths:

    html = page_path.read_text(encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")



    for image in images:
        src = image.get("src")
        alt = image.get("alt")

        print("Source:", src)

        control = image.find_parent(["a", "button"])

        if control is not None:
            print("Inside:", control.name)
            print("Control text:", repr(control.get_text(" ", strip=True)))
            print("Control aria-label:", repr(control.get("aria-label")))
        else:
            print("Inside: No enclosing link or button")

        section = image.find_parent(["figure", "section", "article"])
        nearby_text = ""

        if section is not None:
            nearby_text = section.get_text(" ", strip=True)
            print("Nearby text:", nearby_text[:700])

        if alt is None:
            print("Result: Missing alt attribute — needs checking.")
        elif alt.strip() == "":
            print("Result: Empty alt text — inspect the image's purpose.")
        else:
            print("Result: Description present:", alt)


        print()
        record = {
            "page": page_path.name,
            "image_id": image.get("id"),
            "src": src,
            "image_path": str((page_path.parent / src).resolve().relative_to(Path(__file__).resolve().parent)),
            "image_html": str(image),
            "context_html": (
                str(section) if section is not None else ""
            ),
            "alt": alt,
            "nearby_text": nearby_text,
            "inside_control": control is not None,
            "control_type": control.name if control is not None else None,
            "control_text": (
                control.get_text(" ", strip=True)
                if control is not None else ""
            ),
            "control_aria_label": (
                control.get("aria-label")
                if control is not None else None
            )
        }

        records.append(record)



for record in records:
    apply_rules(record)

output_path = Path(__file__).parent / "observations.json"

output_path.write_text(
    json.dumps(records, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("Saved", len(records), "image records to:", output_path)
print("Pages scanned:", len(page_paths))
print("Image records:", len(records))
