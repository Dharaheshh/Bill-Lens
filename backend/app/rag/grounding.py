"""Grounding validator for policy term extraction."""
import logging
import re

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"[\d,]+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text.lower()).strip()


def _strip_commas(s: str) -> str:
    return s.replace(",", "")


def validate_term(
    key: str,
    quote: str | None,
    chunk_text: str | None,
    value: float | bool | None,
) -> bool:
    """
    Returns True if grounding passes.
    Rules:
    (a) quote (normalized) must be substring of chunk_text (normalized)
    (b) for numeric terms, the number (commas stripped) must appear in quote digits
    (c) for proportionate_deduction, quote must contain 'proportion'
    """
    if not quote or not chunk_text:
        logger.debug("Grounding failed for %s: missing quote or chunk_text", key)
        return False

    norm_quote = _normalize(quote)
    norm_chunk = _normalize(chunk_text)

    if norm_quote not in norm_chunk:
        logger.debug("Grounding failed for %s: quote not in chunk", key)
        return False

    if key == "proportionate_deduction":
        if "proportion" not in norm_quote:
            logger.debug("Grounding failed for proportionate_deduction: 'proportion' not in quote")
            return False
        return True

    if key in ("sum_insured", "room_rent_cap", "copay_pct"):
        if value is None:
            return False
        # The numeric value (commas stripped) must appear as digits in quote
        val_str = _strip_commas(str(int(value) if isinstance(value, float) and value == int(value) else value))
        quote_digits = [_strip_commas(m) for m in _DIGIT_RE.findall(quote)]
        if val_str not in quote_digits:
            # Try percentage form for copay
            if key == "copay_pct" and str(int(value)) in [_strip_commas(d) for d in quote_digits]:
                return True
            logger.debug("Grounding failed for %s: value %s not found in quote digits %s", key, val_str, quote_digits)
            return False

    return True
