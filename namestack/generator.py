"""Name generation: keyword combinators, phonetic morphs, blends, and TLD hacks.

This module is pure (no network) and fast: it produces the candidate pool that
the async availability checker consumes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from .phonetics import jaro_winkler_similarity, metaphone

if TYPE_CHECKING:
    from .inspire import Idea

__all__ = [
    "Candidate",
    "SUFFIXES",
    "PREFIXES",
    "HACK_TLDS",
    "generate",
    "phonetic_variants",
    "blend",
    "match_score",
]

# Startup-style suffix and prefix combinators.
SUFFIXES: tuple[str, ...] = (
    "ify", "ly", "hq", "io", "ful", "able", "o", "a", "er", "ster", "ish",
    "pad", "stack", "base", "app", "box", "kit", "hub", "labs", "works",
    "logic", "gen", "matic", "phonic", "ista", "let", "flow", "gram", "spot",
    "link", "wise", "lyze", "sy", "lee", "co", "hive", "nest", "loop", "sync",
    "verse", "sphere", "byte", "dex", "ium", "ex", "os", "up", "fi", "go",
    "zip", "ology", "orama", "scape",
)

PREFIXES: tuple[str, ...] = (
    "pure", "active", "re", "get", "my", "go", "try", "pro", "ultra", "hyper",
    "neo", "meta", "omni", "super", "micro", "nano", "bright", "vivid", "next",
    "open", "smart", "cloud", "synth", "poly", "trans", "astro", "turbo",
    "cyber", "quantum", "deep", "pixel", "blue", "gold", "silver", "crystal",
    "nova", "aero", "bio", "eco", "geo", "hydro", "infra", "proto", "retro",
    "tele", "uni",
)

# Real ccTLDs that frequently complete an English word (domain hacks).
HACK_TLDS: tuple[str, ...] = (
    "ly", "fi", "io", "co", "me", "us", "it", "to", "gg", "sh", "ai",
    "am", "fm", "so", "im", "is", "tv", "cc", "de", "in", "at", "be", "ch",
    "id", "ie", "li", "no", "nu", "nz", "se", "si", "sk", "uk",
)

# Phoneme-grapheme swaps for "sound-alike" respellings.
PHONEME_SWAPS: tuple[tuple[str, str], ...] = (
    ("ph", "f"), ("f", "ph"), ("ck", "k"), ("qu", "kw"),
    ("x", "cks"), ("y", "i"), ("i", "y"), ("z", "s"),
    ("c", "k"), ("k", "c"),
)

# Alternative spellings for vowel clusters (applied to one cluster at a time).
VOWEL_ALTS: dict[str, tuple[str, ...]] = {
    "a": ("ai", "ay", "e"),
    "e": ("ea", "ee", "i"),
    "i": ("y", "ee", "ie"),
    "o": ("oa", "oo", "ou"),
    "u": ("oo", "ue", "ou"),
    "ee": ("i", "ea"),
    "oo": ("u", "ou"),
    "ai": ("a", "ay"),
    "ea": ("e", "ee"),
    "ou": ("o", "u"),
    "ie": ("i", "y"),
    "ay": ("a", "ai"),
}


@dataclass(frozen=True)
class Candidate:
    """A generated domain candidate."""

    domain: str      # full domain, e.g. "spacely.com" or "spoti.fi"
    name: str        # wordmark / stem, e.g. "spacely"
    tld: str         # e.g. "com"
    kind: str        # seed | suffix | prefix | phonetic | blend | hack
    score: int       # 0-100 phonetic/lexical match score vs. seeds
    seeds: tuple[str, ...]
    why: str = ""    # short explanation of where the name came from

    @property
    def is_hack(self) -> bool:
        return self.kind == "hack"


def _clean(word: str) -> str:
    """Normalize a single token to an ASCII alphanumeric stem."""
    word = unicodedata.normalize("NFKD", word or "")
    word = word.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", word.lower())


def phonetic_variants(word: str) -> list[str]:
    """Produce a bounded set of sound-alike respellings of *word*.

    Uses Double-Metaphone-style phoneme-grapheme swaps plus vowel morphing,
    powered by the ``jellyfish`` phonetic primitives for scoring downstream.
    """
    word = _clean(word)
    if len(word) < 2:
        return []
    out: set[str] = set()

    # One phoneme-grapheme swap at a time.
    for a, b in PHONEME_SWAPS:
        if a in word:
            out.add(word.replace(a, b, 1))

    # Drop a trailing silent 'e'.
    if word.endswith("e") and len(word) > 3:
        out.add(word[:-1])

    # Collapse doubled consonants ("sunn" -> "sun").
    collapsed = re.sub(r"(.)\1+", r"\1", word)
    if collapsed != word:
        out.add(collapsed)

    # Morph one vowel cluster at a time.
    for m in re.finditer(r"[aeiou]+", word):
        cluster = m.group()
        for repl in VOWEL_ALTS.get(cluster, ()):
            variant = word[: m.start()] + repl + word[m.end():]
            if variant != word:
                out.add(variant)

    out.discard(word)
    return sorted(v for v in out if len(v) >= 2)


def blend(a: str, b: str) -> list[str]:
    """Blend two roots by overlap merge and syllable-ish splits."""
    a, b = _clean(a), _clean(b)
    if len(a) < 2 or len(b) < 2:
        return []
    out: set[str] = set()

    # Overlap merges: "space" + "ace" -> "space", "energy" + "gyro" -> ...
    for i in range(2, min(len(a), len(b)) + 1):
        if a[-i:] == b[:i]:
            out.add(a + b[i:])
        if b[-i:] == a[:i]:
            out.add(b + a[i:])

    # Half-half blends.
    ha, hb = len(a) // 2, len(b) // 2
    if ha and hb:
        out.add(a[:ha] + b[hb:])
        out.add(b[:hb] + a[ha:])

    # Head of one + tail of the other.
    out.add(a[: max(1, len(a) - 2)] + b[-2:])
    out.add(b[: max(1, len(b) - 2)] + a[-2:])

    out.discard(a)
    out.discard(b)
    return sorted(v for v in out if len(v) >= 2)


def match_score(name: str, seeds: Sequence[str]) -> int:
    """0-100 score: lexical similarity plus a phonetic-equality bonus."""
    name = _clean(name)
    if not name or not seeds:
        return 0
    best = max(jaro_winkler_similarity(name, s) for s in seeds)
    score = best * 100.0
    key = metaphone(name)
    if key and any(key == metaphone(s) for s in seeds):
        score = min(100.0, score + 10.0)
    return int(round(score))


def generate(
    seeds: Iterable[str],
    tlds: Iterable[str] = ("com", "io", "ai"),
    *,
    include_hacks: bool = True,
    min_score: int = 0,
    max_candidates: Optional[int] = None,
    ideas: Optional[Sequence["Idea"]] = None,
) -> list[Candidate]:
    """Build the candidate pool from seed words.

    Without *ideas* the pool is the classic one: the seeds themselves,
    prefix/suffix combinations, phonetic respellings and pairwise blends,
    scored by similarity to the seeds.

    With *ideas* (from ``inspire.ideas_for`` and/or the LLM) those names are
    used instead, scored by brandability, and interleaved across vibes so a
    ``max_candidates`` cap keeps every vibe represented.
    """
    seed_list = [s for s in (_clean(s) for s in seeds) if len(s) >= 2]
    tld_list = [_clean(t) for t in tlds]
    if not seed_list or not tld_list:
        return []

    # name -> (kind, why, score, order)
    stems: dict[str, tuple[str, str, int, tuple[int, int]]] = {}

    if ideas is not None:
        from .inspire import brand_score

        rank_in_vibe: dict[str, int] = {}
        vibe_order: dict[str, int] = {}
        for idea in ideas:
            name = _clean(idea.name)
            if len(name) < 2 or name in stems:
                continue
            vibe_order.setdefault(idea.vibe, len(vibe_order))
            rank = rank_in_vibe.get(idea.vibe, 0)
            rank_in_vibe[idea.vibe] = rank + 1
            stems[name] = (idea.vibe, idea.why, brand_score(name), (rank, vibe_order[idea.vibe]))
    else:
        def add(name: str, kind: str) -> None:
            name = _clean(name)
            if len(name) >= 2 and name not in stems:
                stems[name] = (kind, "", match_score(name, seed_list), (0, 0))

        for s in seed_list:
            add(s, "seed")
            for suf in SUFFIXES:
                add(s + suf, "suffix")
            for pre in PREFIXES:
                add(pre + s, "prefix")
            for variant in phonetic_variants(s):
                add(variant, "phonetic")
        for a, b in combinations(seed_list, 2):
            for merged in blend(a, b):
                add(merged, "blend")

    candidates: dict[str, Candidate] = {}
    order: dict[str, tuple[int, int]] = {}
    for name, (kind, why, score, pos) in stems.items():
        if score < min_score:
            continue
        for tld in tld_list:
            domain = f"{name}.{tld}"
            if domain not in candidates:
                candidates[domain] = Candidate(domain, name, tld, kind, score, tuple(seed_list), why)
                order[domain] = pos
        if include_hacks:
            for htld in HACK_TLDS:
                if name.endswith(htld) and len(name) > len(htld) + 2:
                    base = name[: -len(htld)]
                    domain = f"{base}.{htld}"
                    if domain not in candidates:
                        hack_kind = "hack" if ideas is None else kind
                        hack_why = f"domain hack: {base}.{htld} spells '{name}'"
                        candidates[domain] = Candidate(
                            domain, base, htld, hack_kind, score, tuple(seed_list), hack_why
                        )
                        order[domain] = pos

    if ideas is not None:
        result = sorted(candidates.values(), key=lambda c: (order[c.domain], c.domain))
    else:
        result = sorted(candidates.values(), key=lambda c: (-c.score, c.domain))
    if max_candidates:
        result = result[:max_candidates]
    return result
