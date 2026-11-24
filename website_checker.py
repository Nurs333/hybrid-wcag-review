"""Capture image evidence from one public page, then optionally call OpenAI."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

from bs4 import BeautifulSoup
from PIL import Image

from ai_check import DEFAULT_MODEL, assessment_key, check_image
from image_rules import apply_rules


PROJECT = Path(__file__).resolve().parent
CONTEXT_LIMIT = 24000

# This function runs against the rendered DOM, including JavaScript-created images.
EXTRACT_IMAGE = r"""(img) => {
    const labelText = (element) => (element?.getAttribute('aria-labelledby') || '')
        .split(/\s+/).filter(Boolean)
        .map(id => document.getElementById(id)?.textContent || '').join(' ').trim();
    const control = img.closest('a[href], button, [role="button"], [role="link"]');
    const container = img.closest('figure, article, section, li, td') || img.parentElement;
    const context = container?.outerHTML || '';
    const style = getComputedStyle(img);
    const rect = img.getBoundingClientRect();
    const visible = rect.width > 0 && rect.height > 0 &&
        style.display !== 'none' && style.visibility !== 'hidden' &&
        style.visibility !== 'collapse' && Number(style.opacity) !== 0;
    const otherAlts = control ? Array.from(control.querySelectorAll('img'))
        .filter(other => other !== img && !other.closest('[aria-hidden="true"]'))
        .map(other => other.getAttribute('alt') || '').join(' ').trim() : '';
    return {
        image_id: img.id || null,
        src: img.currentSrc || img.src || '',
        alt: img.getAttribute('alt'),
        image_html: img.outerHTML,
        context_html: context.slice(0, 24000),
        context_truncated: context.length > 24000,
        nearby_text: (container?.innerText || '').slice(0, 12000),
        inside_control: Boolean(control),
        control_type: control?.tagName.toLowerCase() || null,
        control_text: control?.innerText.trim() || '',
        control_aria_label: control?.getAttribute('aria-label') || null,
        control_labelledby_text: labelText(control),
        control_other_image_alt: otherAlts,
        image_aria_label: img.getAttribute('aria-label'),
        image_labelledby_text: labelText(img),
        aria_hidden: Boolean(img.closest('[aria-hidden="true"]')),
        role: img.getAttribute('role'),
        visible: visible,
        loaded: img.complete && img.naturalWidth > 0,
        rendered_width: rect.width,
        rendered_height: rect.height
    };
}"""


def validate_url(value, allow_private=False):
    value = value.strip()
    if not value:
        raise ValueError("Enter a public webpage URL.")
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use an http:// or https:// webpage URL.")
    parsed.port  # Validate an explicitly supplied port before navigation.
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Use a URL without embedded login credentials.")
    if not allow_private:
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError("Use a publicly reachable website address.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Use a publicly reachable website address.")
    return value


def save_run(run):
    path = Path(run["run_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement keeps the previous complete checkpoint on interruption.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        json.dump(run, output, indent=2, ensure_ascii=False)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PublicRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allow_private=False):
        self.allow_private = allow_private

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_url(newurl, self.allow_private)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_resource(url, limit, allow_private=False):
    validate_url(url, allow_private)
    opener = build_opener(PublicRedirectHandler(allow_private))
    request = Request(url, headers={"User-Agent": "ImageAccessibilityPrototype/1.0"})
    with opener.open(request, timeout=20) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Resource exceeds the capture size limit.")
        return body, response.headers, response.url


def labelledby_text(element, soup):
    if element is None:
        return ""
    names = []
    for identifier in element.get("aria-labelledby", "").split():
        label = soup.find(id=identifier)
        if label is not None:
            names.append(label.get_text(" ", strip=True))
    return " ".join(names)


def extract_html_records(markup, page_url, max_images):
    soup = BeautifulSoup(markup, "html.parser")
    base = soup.find("base", href=True)
    base_url = urljoin(page_url, base["href"]) if base else page_url
    images = soup.find_all("img")
    records = []
    for image in images[:max_images]:
        control = image.find_parent(["a", "button"])
        container = image.find_parent(["figure", "article", "section", "li", "td"]) or image.parent
        context = str(container)
        # Prefer lazy-loading attributes when the source is a placeholder.
        source = image.get("data-src") or image.get("data-original") or image.get("src") or ""
        if not source and image.get("srcset"):
            source = image["srcset"].split(",")[-1].strip().split()[0]
        records.append({
            "image_id": image.get("id"),
            "src": urljoin(base_url, source) if source else "",
            "alt": image.get("alt"),
            "image_html": str(image),
            "context_html": context[:CONTEXT_LIMIT],
            "context_truncated": len(context) > CONTEXT_LIMIT,
            "nearby_text": container.get_text(" ", strip=True)[:12000],
            "inside_control": control is not None,
            "control_type": control.name if control is not None else None,
            "control_text": control.get_text(" ", strip=True) if control is not None else "",
            "control_aria_label": control.get("aria-label") if control is not None else None,
            "control_labelledby_text": labelledby_text(control, soup),
            "control_other_image_alt": " ".join(
                other.get("alt") or "" for other in control.find_all("img") if other is not image
            ) if control is not None else "",
            "image_aria_label": image.get("aria-label"),
            "image_labelledby_text": labelledby_text(image, soup),
            "aria_hidden": image.get("aria-hidden") == "true" or image.find_parent(attrs={"aria-hidden": "true"}) is not None,
            "role": image.get("role"),
            "visible": None,
            "capture_method": "source_image",
        })
    title = soup.title.get_text(" ", strip=True) if soup.title else page_url
    return title, records, len(images)


def capture_source_image(record, destination, allow_private=False):
    source = record["src"]
    if source.startswith("data:image/"):
        header, encoded = source.split(",", 1)
        if ";base64" not in header or len(encoded) > 20_000_000:
            raise ValueError("Unsupported or oversized embedded image.")
        body = base64.b64decode(encoded, validate=True)
    else:
        body, _, _ = fetch_resource(source, 12_000_000, allow_private)
    with Image.open(BytesIO(body)) as image:
        if image.width * image.height > 25_000_000:
            raise ValueError("Image is too large to capture.")
        image.convert("RGBA").save(destination, format="PNG")


def capture_browser(run, max_images, allow_private=False, executable_path=None, progress=None):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
            approved_hosts = set()

            def route_request(route):
                resource = route.request.url
                try:
                    host = urlsplit(resource).hostname
                    if host not in approved_hosts:
                        validate_url(resource, allow_private)
                        approved_hosts.add(host)
                    route.continue_()
                except (ValueError, OSError):
                    route.abort()

            context.route("**/*", route_request)
            page = context.new_page()
            response = page.goto(run["requested_url"], wait_until="domcontentloaded", timeout=30000)
            if response is not None and response.status >= 400:
                raise ValueError(f"The page returned HTTP {response.status}.")
            page.wait_for_timeout(1000)
            # Bounded scrolling triggers common lazy-loading implementations.
            for _ in range(8):
                at_bottom = page.evaluate("window.scrollY + window.innerHeight >= document.documentElement.scrollHeight")
                if at_bottom:
                    break
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(200)
            page.evaluate("window.scrollTo(0, 0)")
            run["url"] = validate_url(page.url, allow_private)
            run["title"] = page.title()
            handles = page.locator("img").element_handles()
            run["images_found"] = len(handles)
            for index, handle in enumerate(handles[:max_images], 1):
                record = {"image_key": f"image_{index:03d}", "page": run["url"], "scan_id": run["scan_id"]}
                try:
                    metadata = handle.evaluate(EXTRACT_IMAGE)
                    if metadata["visible"]:
                        handle.scroll_into_view_if_needed(timeout=3000)
                        try:
                            handle.wait_for_element_state("stable", timeout=1500)
                            page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=handle, timeout=3000)
                        except Exception:
                            pass
                        metadata = handle.evaluate(EXTRACT_IMAGE)
                    record.update(metadata)
                    record["capture_method"] = "rendered_element"
                    if not metadata["visible"]:
                        record["capture_status"] = "not_visible"
                        record["capture_error"] = "The image is hidden or has no rendered dimensions."
                    elif not metadata["loaded"]:
                        record["capture_status"] = "unavailable"
                        record["capture_error"] = "The image did not finish loading."
                    elif metadata["rendered_width"] * metadata["rendered_height"] > 25_000_000:
                        record["capture_status"] = "unavailable"
                        record["capture_error"] = "Rendered image exceeds the capture size limit."
                    else:
                        destination = Path(run["run_path"]).parent / f'{record["image_key"]}.png'
                        handle.screenshot(path=str(destination), timeout=5000)
                        record["image_path"] = str(destination.relative_to(PROJECT))
                        record["capture_status"] = "captured"
                except Exception as error:
                    record["capture_status"] = "unavailable"
                    record["capture_error"] = f"Image capture failed ({type(error).__name__})."
                finish_record(record)
                run["images"].append(record)
                save_run(run)
                if progress:
                    progress(index, min(len(handles), max_images))
        finally:
            browser.close()


def finish_record(record):
    if "image_html" not in record:
        record.update(
            rule_result="needs_review", rule_flags=[],
            rule_reason="Image metadata could not be collected.",
            decision="needs_review", source="capture",
        )
        return
    if len(record["image_html"]) > 8000:
        record["image_html"] = record["image_html"][:8000]
        record["context_truncated"] = True
    if record.get("src", "").startswith("data:") and len(record["src"]) > 200:
        record["src"] = record["src"].split(",", 1)[0] + ",[embedded image]"
    apply_rules(record)
    if record.get("visible") is False:
        record["decision"] = "not_visible"
        record["source"] = "capture"
    elif record["rule_result"] == "potential_issue":
        record["decision"] = "potential_issue"
        record["source"] = "rules"
    else:
        record["decision"] = "needs_review"
        record["source"] = "pending"


def scan_website(url, max_images=12, mode="browser", allow_private=False, progress=None, executable_path=None):
    url = validate_url(url, allow_private)
    if not 1 <= max_images <= 100:
        raise ValueError("Choose between 1 and 100 images for this scan.")
    if mode not in {"browser", "html"}:
        raise ValueError("Choose browser or html mode.")
    scan_id = uuid.uuid4().hex
    directory = PROJECT / "runs" / scan_id
    directory.mkdir(parents=True)
    run = {
        "scan_id": scan_id, "requested_url": url, "url": url, "title": url,
        "mode": mode, "max_images": max_images, "images_found": 0, "images": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "capturing", "run_path": str(directory / "scan.json"),
    }
    save_run(run)
    try:
        if mode == "browser":
            capture_browser(run, max_images, allow_private, executable_path, progress)
        else:
            markup, headers, final_url = fetch_resource(url, 5_000_000, allow_private)
            run["url"] = final_url
            charset = headers.get_content_charset() or "utf-8"
            run["title"], records, run["images_found"] = extract_html_records(markup.decode(charset, errors="replace"), final_url, max_images)
            for index, record in enumerate(records, 1):
                record.update(image_key=f"image_{index:03d}", page=final_url, scan_id=scan_id)
                try:
                    destination = directory / f'{record["image_key"]}.png'
                    capture_source_image(record, destination, allow_private)
                    record.update(image_path=str(destination.relative_to(PROJECT)), capture_status="captured")
                except Exception as error:
                    record.update(capture_status="unavailable", capture_error=f"Image download failed ({type(error).__name__}). Try browser mode.")
                finish_record(record)
                run["images"].append(record)
                save_run(run)
                if progress:
                    progress(index, len(records))
        run["status"] = "captured"
    except Exception as error:
        run.update(status="capture_failed", error=f"{type(error).__name__}: {error}")
        save_run(run)
        raise
    save_run(run)
    return run


def pending_ai_records(run):
    return [record for record in run["images"] if record["rule_result"] == "needs_review" and record["capture_status"] == "captured" and record.get("visible") is not False]


def run_ai(run, model=DEFAULT_MODEL, progress=None, client=None):
    if client is None and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY in the terminal running this app.")
    records = pending_ai_records(run)
    for index, record in enumerate(records, 1):
        try:
            key = assessment_key(record, model)
            if record.get("ai_result", {}).get("assessment_key") != key:
                result = check_image(record, model=model, client=client)
                record.update(ai_result=result, decision=result["decision"], source="AI")
                record.pop("ai_error", None)
        except Exception as error:
            record.pop("ai_result", None)
            record.update(decision="needs_review", source="AI error", ai_error=type(error).__name__)
        save_run(run)
        if progress:
            progress(index, len(records))
    return run


def scan_in_worker(*args, **kwargs):
    # Playwright owns its event loop in a worker, including on Streamlit runtimes.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(scan_website, *args, **kwargs).result()


def main():
    parser = argparse.ArgumentParser(description="Inspect images on one public webpage.")
    parser.add_argument("url")
    parser.add_argument("--max-images", type=int, default=12)
    parser.add_argument("--mode", choices=["browser", "html"], default="browser")
    parser.add_argument("--ai", action="store_true", help="Send remaining captured images to OpenAI.")
    args = parser.parse_args()
    run = scan_website(args.url, args.max_images, args.mode)
    if args.ai:
        run_ai(run)
    print(f'Captured {len(run["images"])} of {run["images_found"]} image elements.')
    for record in run["images"]:
        print(record["image_key"], record["decision"], record.get("src", "")[:120])
    print("Saved scan:", run["run_path"])


if __name__ == "__main__":
    main()
