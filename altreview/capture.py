"""Chromium DOM captures paired with actual browser-computed accessible names."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from queue import Empty, Queue
import time
from urllib.parse import urlsplit

from . import SCHEMA_VERSION
from .facts import assess
from .network import public_url
from . import storage

SELECTOR = 'img, [role="img"], input[type="image"]'
INVENTORY_LIMIT = 300

EXTRACT = r"""(el) => {
  const control = el.closest('a[href],button,input[type="image"],[role="button"],[role="link"]');
  const container = el.closest('figure,li,article,section,td') || el.parentElement;
  const box = el.getBoundingClientRect();
  const visible = el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && box.width > 0 && box.height > 0;
  const caption = el.closest('figure')?.querySelector('figcaption');
  const heading = container?.querySelector('h1,h2,h3,h4');
  return {
    id:el.getAttribute('data-altreview-node'), tag:el.tagName.toLowerCase(),
    src:el.currentSrc || el.getAttribute('src') || '', alt:el.getAttribute('alt'),
    title:el.getAttribute('title'), role:el.getAttribute('role'),
    aria_label:el.getAttribute('aria-label'), aria_labelledby:el.getAttribute('aria-labelledby'),
    aria_hidden:!!el.closest('[aria-hidden="true"]'), layout_visible:visible,
    control_ref:control ? (control.getAttribute('data-altreview-control') || 'unmapped') : null,
    control_tag:control?.tagName.toLowerCase() || null, control_href:control?.getAttribute('href') || null,
    caption:caption?.innerText.trim().slice(0,1500) || '',
    nearby_heading:heading?.innerText.trim().slice(0,300) || '',
    nearby_text:(container?.innerText || '').trim().slice(0,2000),
    loaded:el.tagName !== 'IMG' || (el.complete && el.naturalWidth > 0),
    bounds:{x:box.x,y:box.y,width:box.width,height:box.height},
    markup:el.cloneNode(false).outerHTML.slice(0,1500)
  };
}"""

VISIBLE_REGION = r"""(el) => {
  let r = el.getBoundingClientRect();
  let x=Math.max(0,r.left), y=Math.max(0,r.top), right=Math.min(innerWidth,r.right), bottom=Math.min(innerHeight,r.bottom);
  for(let p=el.parentElement;p;p=p.parentElement){
    const s=getComputedStyle(p), b=p.getBoundingClientRect();
    if(/hidden|clip|auto|scroll/.test(s.overflowX)){x=Math.max(x,b.left);right=Math.min(right,b.right);}
    if(/hidden|clip|auto|scroll/.test(s.overflowY)){y=Math.max(y,b.top);bottom=Math.min(bottom,b.bottom);}
  }
  return {x:x+scrollX,y:y+scrollY,width:Math.max(0,right-x),height:Math.max(0,bottom-y),
    partial:(Math.max(0,right-x)*Math.max(0,bottom-y)) < r.width*r.height*.98};
}"""


def _backend_id(session, root, selector):
    node_id = session.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
    if not node_id:
        return None
    return session.send("DOM.describeNode", {"nodeId": node_id})["node"]["backendNodeId"]


def _ax(session, backend_id):
    if backend_id is None:
        return {"available": False, "error": "The DOM node could not be located."}
    try:
        nodes = session.send("Accessibility.getPartialAXTree", {"backendNodeId": backend_id, "fetchRelatives": False})["nodes"]
        node = next((node for node in nodes if node.get("backendDOMNodeId") == backend_id), None)
        if node is None:
            return {"available": False, "error": "Chromium returned no matching accessibility node."}
        sources = []
        for source in (node.get("name") or {}).get("sources", []):
            sources.append({key: source[key] for key in ("type", "attribute", "nativeSource", "superseded", "invalid", "value", "attributeValue") if key in source})
        return {"available": True, "ignored": node.get("ignored", False),
                "role": (node.get("role") or {}).get("value", ""),
                "name": (node.get("name") or {}).get("value", ""), "name_sources": sources,
                "ignored_reasons": [value["name"] for value in node.get("ignoredReasons", [])]}
    except Exception as error:
        return {"available": False, "error": type(error).__name__}


def collect(page, run, capture_limit=12, progress=None):
    """Names are checked for the whole bounded inventory; only screenshots use the budget."""
    started = time.monotonic()
    tagged = page.evaluate("""({selector,limit}) => {
      const nodes=Array.from(document.querySelectorAll(selector));let controlNumber=0;
      nodes.slice(0,limit).forEach((node,index)=>{
        node.setAttribute('data-altreview-node',`image_${String(index+1).padStart(3,'0')}`);
        const c=node.closest('a[href],button,input[type="image"],[role="button"],[role="link"]');
        if(c && !c.hasAttribute('data-altreview-control'))c.setAttribute('data-altreview-control',`control_${++controlNumber}`);
      });
      return {count:nodes.length,ids:nodes.slice(0,limit).map(n=>n.getAttribute('data-altreview-node'))};
    }""", {"selector": SELECTOR, "limit": INVENTORY_LIMIT})
    run["discovered"] = tagged["count"]
    if tagged["count"] > INVENTORY_LIMIT:
        run["warnings"].append(f"Inventory capped at {INVENTORY_LIMIT} elements; some names were not checked.")
    session = page.context.new_cdp_session(page)
    session.send("DOM.enable")
    session.send("Accessibility.enable")
    root = session.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    control_backends = {}
    for index, identifier in enumerate(tagged["ids"], 1):
        selector = f'[data-altreview-node="{identifier}"]'
        locator = page.locator(selector)
        record = {"id": identifier, "capture_status": "unavailable", "layout_visible": False}
        try:
            record.update(locator.evaluate(EXTRACT))
            backend = _backend_id(session, root, selector)
            record["image_ax"] = _ax(session, backend)
            reference = record.get("control_ref")
            if reference:
                if reference not in control_backends:
                    control_backends[reference] = _backend_id(session, root, f'[data-altreview-control="{reference}"]')
                record["control_ax"] = _ax(session, control_backends[reference])
            record["capture_status"] = "not_selected" if record["layout_visible"] else "hidden"
            record["name_snapshot_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as error:
            record["capture_error"] = f"Metadata unavailable: {type(error).__name__}"
            record["image_ax"] = {"available": False}
        assess(record)
        run["images"].append(record)
        if progress:
            progress("names", index, len(tagged["ids"]))
    storage.save(run)
    captured = 0
    for record in run["images"]:
        if captured >= capture_limit or time.monotonic() - started > 90:
            break
        if record["capture_status"] != "not_selected":
            continue
        locator = page.locator(f'[data-altreview-node="{record["id"]}"]')
        try:
            locator.scroll_into_view_if_needed(timeout=2500)
            page.wait_for_timeout(120)
            before = locator.evaluate(EXTRACT)
            record.update(before)
            record["image_ax"] = _ax(session, _backend_id(session, root, f'[data-altreview-node="{record["id"]}"]'))
            if record.get("control_ref"):
                record["control_ax"] = _ax(session, _backend_id(session, root, f'[data-altreview-control="{record["control_ref"]}"]'))
            record["name_snapshot_at"] = datetime.now(timezone.utc).isoformat()
            assess(record)
            if not before["loaded"]:
                try:
                    page.wait_for_function("el => el.tagName !== 'IMG' || (el.complete && el.naturalWidth > 0)", arg=locator.element_handle(), timeout=2500)
                except Exception:
                    raise ValueError("Image did not finish loading.")
            region = locator.evaluate(VISIBLE_REGION)
            if region["width"] < 2 or region["height"] < 2:
                record.update(capture_status="clipped", capture_error="No visible pixels remained after clipping by the page layout.")
                continue
            if region["width"] * region["height"] > 12_000_000:
                raise ValueError("Rendered image exceeds the pixel budget.")
            name = record["id"] + ".png"
            destination = storage.run_directory(run) / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(destination), clip={key: region[key] for key in ("x", "y", "width", "height")}, animations="disabled", timeout=5000)
            after = locator.evaluate(EXTRACT)
            if any(before.get(key) != after.get(key) for key in ("src", "alt", "control_ref")):
                destination.unlink(missing_ok=True)
                raise ValueError("Image or naming metadata changed during capture. Scan again.")
            record.update(capture_status="captured", capture_file=name, capture_partial=region["partial"],
                          image_sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
            captured += 1
        except Exception as error:
            record.update(capture_status="unavailable", capture_error=str(error)[:250])
        if progress:
            progress("images", captured, capture_limit)
        storage.save(run)
    if captured < capture_limit and time.monotonic() - started > 90:
        run["warnings"].append("The capture time budget was reached; remaining images have name evidence but no screenshot.")
    run.update(status="complete", elapsed_seconds=round(time.monotonic() - started, 3))
    storage.save(run)
    return run


def scan(url=None, capture_limit=12, *, markup=None, progress=None, executable_path=None):
    if not 0 <= capture_limit <= 50:
        raise ValueError("Choose between 0 and 50 visual captures.")
    url = "demo://altreview" if markup is not None else public_url(url or "")
    run = storage.new_run(url, capture_limit)
    storage.save(run)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable_path or os.environ.get("ALTREVIEW_BROWSER"))
        context = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block")
        approved_hosts = set()

        def route_request(route):
            resource = route.request.url
            try:
                parsed = urlsplit(resource)
                if parsed.scheme in {"data", "blob"}:
                    route.continue_()
                    return
                if markup is not None:
                    route.abort()
                    return
                if parsed.hostname not in approved_hosts:
                    public_url(resource)
                    approved_hosts.add(parsed.hostname)
                route.continue_()
            except Exception:
                route.abort()

        context.route("**/*", route_request)
        page = context.new_page()
        try:
            if markup is not None:
                page.set_content(markup, wait_until="load")
            else:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if response and response.status >= 400:
                    raise ValueError(f"The page returned HTTP {response.status}.")
                page.wait_for_timeout(700)
                for _ in range(8):
                    if page.evaluate("scrollY+innerHeight>=document.documentElement.scrollHeight"):
                        break
                    page.evaluate("scrollBy(0,innerHeight)")
                    page.wait_for_timeout(150)
                page.evaluate("scrollTo(0,0)")
                run["url"] = public_url(page.url)
            run["title"] = page.title() or run["url"]
            run["browser_version"] = browser.version
            return collect(page, run, capture_limit, progress)
        except Exception as error:
            run.update(status="error", error=str(error)[:400])
            storage.save(run)
            raise
        finally:
            browser.close()


def scan_in_worker(*args, **kwargs):
    # Streamlit calls must remain on the script thread, never the browser worker.
    callback = kwargs.pop("progress", None)
    updates = Queue()
    kwargs["progress"] = lambda *event: updates.put(event)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(scan, *args, **kwargs)
        while not future.done() or not updates.empty():
            try:
                event = updates.get(timeout=0.1)
                if callback:
                    callback(*event)
            except Empty:
                pass
        return future.result()
