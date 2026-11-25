"""Compact captured semantics and check the text evidence behind local passes.

These checks can reject unsupported passes. They do not compute the full browser
accessible-name algorithm or prove that a description matches an image.
"""

from html import unescape
import json
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

VERSION = "quoted-evidence-v2"
MEDIA_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif")
SEMANTIC_ATTRIBUTES = {"id", "alt", "title", "role", "href", "aria-label", "aria-labelledby", "aria-describedby", "aria-hidden", "hidden", "scope", "headers"}


def normalize(value):
    return " ".join(unescape(value or "").split()).casefold()


def alt_kind(value):
    if value is None:
        return "missing"
    text = normalize(value)
    if not text:
        return "empty"
    if text.rstrip(".!?") in {"image", "photo", "picture"}:
        return "generic"
    if unquote(unquote(text)).endswith(MEDIA_SUFFIXES):
        return "filename"
    return "text"


def target_in_context(task, soup):
    """Only select a unique target; a neighbouring image is not naming evidence."""
    images = soup.find_all("img")
    if task.get("image_id"):
        matches = soup.find_all("img", id=task["image_id"])
        if len(matches) == 1:
            return matches[0]
    image = BeautifulSoup(task.get("image_html") or "", "html.parser").find("img")
    if image:
        source = image.get("src") or image.get("data-src")
        if source:
            matches = [candidate for candidate in images if source in {candidate.get("src"), candidate.get("data-src")} and candidate.get("alt") == image.get("alt")]
            if len(matches) == 1:
                return matches[0]
    return images[0] if len(images) == 1 else None


def compact_html(markup):
    soup = BeautifulSoup(markup or "", "html.parser")
    for element in soup.find_all(["script", "style", "svg", "noscript", "template"]):
        if element.parent is not None:
            element.decompose()
    for element in soup.find_all(True):
        element.attrs = {key: value for key, value in element.attrs.items() if key in SEMANTIC_ATTRIBUTES}
        if element.get("href"):
            element["href"] = element["href"][:200]
    return " ".join(str(soup).split())


def local_context(task, limit=6000):
    soup = BeautifulSoup(task.get("context_html") or "", "html.parser")
    image = target_in_context(task, soup)
    image_markup = BeautifulSoup(task.get("image_html") or "", "html.parser").find("img")
    control = image.find_parent(["a", "button"]) if image is not None else None
    if control is None and image is not None:
        control = image.find_parent(attrs={"role": ["button", "link"]})
    present = bool(task.get("inside_control") or task.get("control_type") or ("inside_control" not in task and control is not None))

    # Captured fields take precedence over inference from serialized markup.
    def field(name, fallback=""):
        value = task.get(name)
        return value if value is not None else fallback

    image_title = image_markup.get("title", "") if image_markup is not None else ""
    control_title = control.get("title", "") if control is not None else ""
    image_names = {
        "aria_label": field("image_aria_label", image_markup.get("aria-label", "") if image_markup is not None else ""), "labelledby_text": field("image_labelledby_text"),
        "title": image_title,
    }
    control_names = {
        "aria_label": field("control_aria_label", control.get("aria-label", "") if control is not None else ""), "labelledby_text": field("control_labelledby_text"),
        "text_inside_control": field("control_text", control.get_text(" ", strip=True) if control is not None else ""),
        "other_image_alt": field("control_other_image_alt"), "title": control_title,
    }
    if not present:
        control_names = {key: "" for key in control_names}
    context = {
        "alt": task.get("alt"), "alt_state": alt_kind(task.get("alt")),
        "image_names": image_names, "inside_control": present,
        "control_type": field("control_type", control.name if control is not None else None) if present else None,
        "control_names": control_names,
        "nearby_text_outside_name": task.get("nearby_text") or "",
        "role": task.get("role"), "aria_hidden": task.get("aria_hidden"),
        "image_html": compact_html(task.get("image_html")),
        "context_html": compact_html(task.get("context_html")),
        "context_truncated": bool(task.get("context_truncated")),
    }
    # Remove implementation markup before clipping useful text and naming fields.
    for key, maximum in (("context_html", 1800), ("nearby_text_outside_name", 1400), ("image_html", 500)):
        if len(context[key]) > maximum:
            context[key] = context[key][:maximum]
            context["context_truncated"] = True
    for names in (image_names, control_names):
        for key, value in names.items():
            if isinstance(value, str) and len(value) > 400:
                names[key] = value[:400]
                context["context_truncated"] = True
    if isinstance(context["alt"], str) and len(context["alt"]) > 1000:
        context["alt"] = context["alt"][:1000]
        context["context_truncated"] = True
    while len(json.dumps(context, ensure_ascii=False)) > limit:
        fields = ["context_html", "nearby_text_outside_name", "image_html"]
        key = max(fields, key=lambda name: len(context[name]))
        if not context[key]:
            # Naming strings are bounded too; the default limit is never reached here.
            raise ValueError("Local naming evidence exceeds the context budget.")
        context[key] = context[key][:len(context[key]) // 2]
        context["context_truncated"] = True
    return context


def validate_pass(parsed, context):
    result = dict(parsed)
    result.update(model_decision=parsed["decision"], model_reason=parsed["reason"], validation_issues=[])
    if parsed["decision"] != "pass":
        return result
    names = [value for value in context["image_names"].values() if normalize(value)]
    control_names = [value for value in context["control_names"].values() if normalize(value)]
    meaningful_alt = context["alt"] if context["alt_state"] == "text" else ""
    available_names = names + control_names + ([meaningful_alt] if meaningful_alt else [])
    quote = normalize(parsed.get("supporting_text"))
    nearby = context["nearby_text_outside_name"]
    quoted_name = bool(quote) and any(quote in normalize(value) for value in available_names)
    quoted_nearby = bool(quote) and quote in normalize(nearby)
    explicit_decorative = context["role"] in {"none", "presentation"} or context["aria_hidden"] is True
    issues = result["validation_issues"]
    if context["inside_control"] and not available_names:
        issues.append("The captured link/button has no name evidence. A sibling caption or the photo's visible subject does not name the control.")
    if not quoted_name and not quoted_nearby and not (explicit_decorative and not context["inside_control"]):
        issues.append("The pass has no exact quotation from a meaningful alternative, control name, or equivalent nearby text. Decoration cannot be established from appearance alone.")
    if issues:
        result["decision"] = "uncertain"
        result["reason"] = "Pass requires review: " + " ".join(issues)
    return result


def supporting_choices(context):
    """The decoder may cite captured text, never a freshly invented description."""
    values = list(context["image_names"].values()) + list(context["control_names"].values())
    if context["alt_state"] == "text":
        values.insert(0, context["alt"])
    nearby = context["nearby_text_outside_name"]
    values += [nearby] + re.split(r"(?<=[.!?])\s+|\n+", nearby)
    choices = [""]
    for value in values:
        value = " ".join((value or "").split())[:160]
        if value and normalize(value) not in {normalize(choice) for choice in choices}:
            choices.append(value)
    return choices
