"""Business objective: protect explicit product attributes from loss, conflict, or hallucination.

Technical description: verifies conservative extraction and conflict/unsupported-attribute detection.
"""

from invoice_canonicalizer.domain.attributes import conflicting_attributes, extract_attributes, unsupported_attributes


def test_extracts_only_explicit_attributes() -> None:
    assert extract_attributes("T-Shirt White Polarbear") == {"color": "white", "category_hint": "t-shirt"}
    assert extract_attributes("Leather Jacket Midnight") == {"material": "leather", "category_hint": "jacket"}


def test_conflicts_and_unsupported_are_detected() -> None:
    assert conflicting_attributes({"color": "white"}, {"color": "beige"}) == ("color",)
    assert unsupported_attributes({"material": "cotton"}, {"material": "cotton", "color": "red"}) == ("color",)
