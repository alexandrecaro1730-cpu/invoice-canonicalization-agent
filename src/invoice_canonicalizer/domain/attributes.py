"""Business objective: prevent canonicalization from losing or inventing critical product attributes.

Technical description: extracts a conservative attribute set and detects candidate conflicts deterministically.
"""

from __future__ import annotations

from invoice_canonicalizer.utils.text import normalize_text, tokenize

_COLOR_TERMS = {
    "black": "black",
    "white": "white",
    "beige": "beige",
    "blue": "blue",
    "red": "red",
    "green": "green",
    "grey": "grey",
    "gray": "grey",
    "brown": "brown",
    "yellow": "yellow",
}
_MATERIAL_TERMS = {
    "steel": "steel",
    "leather": "leather",
    "cotton": "cotton",
    "wool": "wool",
    "polyester": "polyester",
    "aluminium": "aluminium",
    "aluminum": "aluminium",
}
_CATEGORY_TERMS = {
    "sneaker": "footwear",
    "sneakers": "footwear",
    "shoe": "footwear",
    "shoes": "footwear",
    "sock": "socks",
    "socks": "socks",
    "short": "shorts",
    "shorts": "shorts",
    "tee": "t-shirt",
    "tshirt": "t-shirt",
    "t-shirt": "t-shirt",
    "jacket": "jacket",
    "component": "components",
    "components": "components",
    "accessory": "components",
    "accessories": "components",
    "fitting": "components",
    "fittings": "components",
}


def extract_attributes(text: str) -> dict[str, str]:
    """Extract only attributes that are explicit in the source text."""
    normalized = normalize_text(text)
    tokens = set(tokenize(normalized))
    attrs: dict[str, str] = {}
    for token, value in _COLOR_TERMS.items():
        if token in tokens:
            attrs["color"] = value
            break
    for token, value in _MATERIAL_TERMS.items():
        if token in tokens:
            attrs["material"] = value
            break
    if "t shirt" in normalized:
        attrs["category_hint"] = "t-shirt"
    else:
        for token, value in _CATEGORY_TERMS.items():
            if token in tokens:
                attrs["category_hint"] = value
                break
    return attrs


def conflicting_attributes(source: dict[str, str], candidate: dict[str, str]) -> tuple[str, ...]:
    """Return protected keys whose explicit values disagree."""
    conflicts = [
        key for key in ("color", "material", "size", "model")
        if key in source and key in candidate and source[key] != candidate[key]
    ]
    return tuple(sorted(conflicts))


def unsupported_attributes(source: dict[str, str], candidate: dict[str, str]) -> tuple[str, ...]:
    """Return protected attributes introduced without support in the source."""
    unsupported = [
        key for key in ("color", "material", "size", "model")
        if key in candidate and key not in source
    ]
    return tuple(sorted(unsupported))
