"""AI layer: photo tagging + lost/found matching.

Uses Claude when ANTHROPIC_API_KEY (or an `ant auth login` profile) is available.
Falls back to a local keyword + location matcher so the demo never breaks.
"""
import base64
import json
import mimetypes
import os
import re
from datetime import date

MODEL = "claude-opus-5-5"

try:
    import anthropic

    _client = anthropic.Anthropic()
    # Probe credentials cheaply: constructing the client doesn't call the API,
    # so only enable AI if some credential source is configured.
    AI_ENABLED = bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.path.isdir(os.path.expanduser("~/.config/anthropic"))
    ) and os.environ.get("DISABLE_AI") != "1"
except Exception:  # SDK missing or misconfigured
    _client = None
    AI_ENABLED = False


# --------------------------------------------------------------------------
# Claude helpers
# --------------------------------------------------------------------------
def _ask_json(content, schema, max_tokens=4000):
    """Call Claude and return parsed JSON that matches `schema`."""
    resp = _client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": schema},
        },
        messages=[{"role": "user", "content": content}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("AI declined the request")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def _image_block(path):
    media = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "category": {"type": "string"},
        "color": {"type": "string"},
        "brand": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["title", "category", "color", "brand", "description"],
    "additionalProperties": False,
}


def describe_photo(path, user_text=""):
    """Turn a photo (+ optional student text) into clean, searchable tags."""
    if not AI_ENABLED:
        return None
    try:
        return _ask_json(
            [
                _image_block(path),
                {
                    "type": "text",
                    "text": (
                        "This photo was posted to a campus lost-and-found board. "
                        f"The student wrote: {user_text!r}\n"
                        "Return a short title (e.g. 'Black boAt earphones'), a category "
                        f"from {CATEGORIES}, the main color, the brand if visible (else ''), "
                        "and a one-sentence description of identifying details "
                        "(stickers, scratches, case, name tags). Don't invent details."
                    ),
                },
            ],
            TAG_SCHEMA,
        )
    except Exception as e:
        print("[ai] describe_photo failed:", e)
        return None


MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


def _item_text(it):
    return (
        f"[id {it['id']}] {it['kind'].upper()}: {it['title']} | category: {it['category']} | "
        f"color: {it['color'] or '-'} | where: {it['location']} | date: {it['item_date']} | "
        f"details: {it['description']} {it['ai_description'] or ''}"
    )


def ai_rank(item, candidates):
    prompt = (
        "You match lost and found reports on a college campus. Reports are messy, "
        "informal and may use Hinglish or slang ('specs' = glasses, 'airdopes' = earbuds).\n\n"
        f"REPORT:\n{_item_text(item)}\n\nCANDIDATES:\n"
        + "\n".join(_item_text(c) for c in candidates)
        + "\n\nScore each candidate 0-100 for how likely it is the SAME physical item. "
        "Weigh object type and distinguishing details most, then color/brand, then "
        "location and date (a found item can't be found before it was lost). "
        "Give a short reason a student would understand. Only include candidates scoring >= 30."
    )
    out = _ask_json([{"type": "text", "text": prompt}], MATCH_SCHEMA)
    valid = {c["id"] for c in candidates}
    return [m for m in out["matches"] if m["id"] in valid]


# --------------------------------------------------------------------------
# Local fallback matcher (no API needed)
# --------------------------------------------------------------------------
CATEGORIES = [
    "ID card", "Electronics", "Earphones", "Bottle", "Calculator", "Bag",
    "Wallet", "Keys", "Books & Notes", "Clothing", "Glasses", "Jewellery", "Other",
]

SYNONYMS = {
    "earphones": ["earphone", "earbuds", "earbud", "airpods", "airdopes", "headphones",
                  "headset", "tws", "buds", "neckband"],
    "bottle": ["flask", "sipper", "tumbler", "milton"],
    "id": ["idcard", "identity", "card", "lanyard"],
    "calculator": ["calc", "casio", "fx991"],
    "phone": ["mobile", "smartphone", "iphone", "android", "cell"],
    "wallet": ["purse", "pouch"],
    "glasses": ["specs", "spectacles", "sunglasses", "goggles", "shades"],
    "charger": ["adapter", "cable", "powerbank"],
    "bag": ["backpack", "sling", "tote"],
    "keys": ["key", "keychain", "keyring"],
    "notebook": ["notes", "book", "register", "diary"],
    "jacket": ["hoodie", "sweater", "sweatshirt"],
}
_CANON = {}
for k, vs in SYNONYMS.items():
    _CANON[k] = k
    for v in vs:
        _CANON[v] = k

COLORS = {"black", "white", "blue", "red", "green", "yellow", "pink", "purple",
          "grey", "gray", "silver", "gold", "brown", "orange", "navy", "transparent"}
STOP = {"a", "an", "the", "my", "i", "lost", "found", "near", "at", "in", "on", "of",
        "with", "and", "it", "is", "was", "has", "have", "some", "someone", "please",
        "left", "this", "that", "for", "to", "from", "one", "item"}


def _tokens(text):
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        out.add(_CANON.get(w, w.rstrip("s") if len(w) > 3 else w))
    return out


def local_rank(item, candidates, zone_of):
    a = _tokens(" ".join([item["title"], item["description"], item["color"] or "",
                          item["ai_description"] or ""]))
    results = []
    for c in candidates:
        b = _tokens(" ".join([c["title"], c["description"], c["color"] or "",
                              c["ai_description"] or ""]))
        overlap = a & b
        text_score = len(overlap) / max(1, min(len(a), len(b)))
        cat = 1.0 if item["category"] == c["category"] else 0.0
        if item["location"] == c["location"]:
            loc = 1.0
        elif zone_of(item["location"]) == zone_of(c["location"]):
            loc = 0.5
        else:
            loc = 0.0
        try:
            gap = abs((date.fromisoformat(item["item_date"]) - date.fromisoformat(c["item_date"])).days)
        except Exception:
            gap = 7
        dt = max(0.0, 1 - gap / 14)
        score = round(100 * (0.45 * text_score + 0.3 * cat + 0.15 * loc + 0.10 * dt))
        ca, cb = (item["color"] or "").lower().strip(), (c["color"] or "").lower().strip()
        if ca and cb and ca not in cb and cb not in ca:
            score -= 20  # different colors: probably a different item
        if score >= 30:
            bits = []
            if cat:
                bits.append(f"same category ({c['category']})")
            words = sorted(overlap - {c["category"].lower()})[:4]
            if words:
                bits.append("shared details: " + ", ".join(words))
            if loc == 1:
                bits.append("same location")
            elif loc == 0.5:
                bits.append("nearby location")
            if gap <= 2:
                bits.append("reported around the same time")
            results.append({"id": c["id"], "score": min(score, 99),
                            "reason": "; ".join(bits).capitalize() or "Similar item"})
    return results


def find_matches(item, candidates, zone_of):
    """Return (matches, engine) sorted best-first."""
    if not candidates:
        return [], "none"
    # Pre-filter with the local matcher so Claude only sees plausible items.
    pre = local_rank(item, candidates, zone_of)
    if AI_ENABLED:
        shortlist_ids = {m["id"] for m in sorted(pre, key=lambda m: -m["score"])[:15]}
        # Also include same-category items the keyword matcher may have missed.
        shortlist_ids |= {c["id"] for c in candidates if c["category"] == item["category"]}
        shortlist = [c for c in candidates if c["id"] in shortlist_ids][:25]
        if shortlist:
            try:
                ms = ai_rank(item, shortlist)
                return sorted(ms, key=lambda m: -m["score"]), "claude"
            except Exception as e:
                print("[ai] ranking failed, using local matcher:", e)
    return sorted(pre, key=lambda m: -m["score"]), "local"
