"""Heuristic parser that turns a raw eBay listing title into structured
card attributes (year, set, parallel, card number, grade) and a
normalized "signature" string used to group comparable listings together
for comps.

This is intentionally conservative: eBay titles are free text written by
individual sellers with no fixed format, so we can only extract what's
reliably patterned (years, grading company + numeric grade, card number)
and otherwise fall back to a normalized bag-of-words signature. Perfect
parsing isn't the goal -- consistent, comparable grouping is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d|203\d)\b")
CARD_NUMBER_RE = re.compile(r"#\s?([A-Za-z]{0,3}-?\d{1,4}[A-Za-z]?)\b")
GRADE_RE = re.compile(
    r"\b(PSA|BGS|SGC|CGC)\s*[- ]?\s*(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5|4|3|2|1)\b",
    re.IGNORECASE,
)
RAW_RE = re.compile(r"\b(RAW|UNGRADED)\b", re.IGNORECASE)

# Ordered so more specific set names are matched before generic "Topps".
KNOWN_SETS = [
    "Topps Chrome Update",
    "Topps Chrome Sapphire",
    "Topps Chrome Black",
    "Topps Chrome",
    "Topps Update",
    "Topps Heritage",
    "Topps Archives",
    "Topps Stadium Club",
    "Topps Finest",
    "Topps Gypsy Queen",
    "Topps Big League",
    "Topps Fire",
    "Topps Allen & Ginter",
    "Topps Series 1",
    "Topps Series 2",
    "Topps Now",
    "Topps",
]

KNOWN_PARALLELS = [
    "Superfractor", "Gold Refractor", "Refractor", "Prism Refractor",
    "Speckle Refractor", "Wave Refractor", "X-Fractor", "Sepia",
    "Black Refractor", "Red Refractor", "Blue Refractor", "Green Refractor",
    "Orange Refractor", "Purple Refractor", "Pink Refractor",
    "Gold", "Black", "Red", "Blue", "Green", "Orange", "Purple", "Pink",
    "Rainbow Foil", "Foilboard", "Sepia Refractor",
]

STOPWORDS = {
    "the", "a", "an", "and", "with", "of", "in", "on", "for", "new",
    "card", "cards", "rc", "rookie", "mlb", "baseball", "hof",
}


@dataclass
class ParsedCard:
    player: str | None
    year: str | None
    card_set: str | None
    parallel: str | None
    card_number: str | None
    grade_company: str | None
    grade_value: str | None
    signature: str


def _extract_year(title: str) -> str | None:
    match = YEAR_RE.search(title)
    return match.group(1) if match else None


def _extract_set(title: str) -> str | None:
    lowered = title.lower()
    for set_name in KNOWN_SETS:
        if set_name.lower() in lowered:
            return set_name
    return None


def _extract_parallel(title: str) -> str | None:
    lowered = title.lower()
    for parallel in KNOWN_PARALLELS:
        if parallel.lower() in lowered:
            return parallel
    return None


def _extract_card_number(title: str) -> str | None:
    match = CARD_NUMBER_RE.search(title)
    return match.group(1).upper() if match else None


def _extract_grade(title: str) -> tuple[str | None, str | None]:
    match = GRADE_RE.search(title)
    if match:
        return match.group(1).upper(), match.group(2)
    if RAW_RE.search(title):
        return None, "RAW"
    return None, None


def _extract_player(title: str, year: str | None, card_set: str | None) -> str | None:
    """Best-effort player name guess: strip known set/parallel/grade/year
    tokens and card-number markers, then take the remaining run of
    capitalized words that looks like a person's name."""
    cleaned = title
    if year:
        cleaned = cleaned.replace(year, " ")
    if card_set:
        cleaned = re.sub(re.escape(card_set), " ", cleaned, flags=re.IGNORECASE)
    cleaned = CARD_NUMBER_RE.sub(" ", cleaned)
    cleaned = GRADE_RE.sub(" ", cleaned)
    cleaned = RAW_RE.sub(" ", cleaned)
    for parallel in KNOWN_PARALLELS:
        cleaned = re.sub(re.escape(parallel), " ", cleaned, flags=re.IGNORECASE)

    tokens = re.findall(r"[A-Za-z'.-]+", cleaned)
    name_tokens = []
    for tok in tokens:
        if tok.lower() in STOPWORDS:
            continue
        if not tok[0].isupper():
            continue
        name_tokens.append(tok)
        if len(name_tokens) == 2:
            break
    return " ".join(name_tokens) if name_tokens else None


def parse_title(title: str) -> ParsedCard:
    year = _extract_year(title)
    card_set = _extract_set(title)
    parallel = _extract_parallel(title)
    card_number = _extract_card_number(title)
    grade_company, grade_value = _extract_grade(title)
    player = _extract_player(title, year, card_set)

    signature_parts = [
        (player or "unknown-player").lower(),
        year or "unknown-year",
        (card_set or "unknown-set").lower(),
        (parallel or "base").lower(),
        (card_number or "no-number").lower(),
        f"{grade_company or 'raw'}-{grade_value or 'ungraded'}".lower(),
    ]
    signature = "|".join(signature_parts)

    return ParsedCard(
        player=player,
        year=year,
        card_set=card_set,
        parallel=parallel,
        card_number=card_number,
        grade_company=grade_company,
        grade_value=grade_value,
        signature=signature,
    )
