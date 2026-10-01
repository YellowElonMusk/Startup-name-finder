"""Phonetic primitives used for scoring and collision matching.

Prefer the fast C-backed ``jellyfish`` implementation when it is installed;
otherwise fall back to a pure-Python implementation of the same algorithms
(standard Metaphone + Jaro-Winkler) so the package keeps working with no
compiled dependencies.
"""

from __future__ import annotations

import re

try:  # pragma: no cover - depends on environment
    import jellyfish as _jellyfish

    HAS_JELLYFISH = True
except ImportError:  # pragma: no cover - exercised only when jellyfish absent
    _jellyfish = None
    HAS_JELLYFISH = False

__all__ = ["metaphone", "jaro_winkler_similarity", "HAS_JELLYFISH"]


def metaphone(word: str) -> str:
    """Return the Metaphone code for *word* (uppercase letters + digits)."""
    if HAS_JELLYFISH:
        return _jellyfish.metaphone(word or "")
    return _metaphone_fallback(word)


def jaro_winkler_similarity(a: str, b: str) -> float:
    """Return Jaro-Winkler similarity in [0.0, 1.0]."""
    if HAS_JELLYFISH:
        return _jellyfish.jaro_winkler_similarity(a or "", b or "")
    return _jaro_winkler_fallback(a, b)


# ---------------------------------------------------------------------------
# Pure-Python fallbacks (faithful ports of the reference algorithms).
# ---------------------------------------------------------------------------

_VOWELS = frozenset("aeiou")


def _is_vowel(c: str) -> bool:
    return c in _VOWELS


def _metaphone_fallback(word: str) -> str:
    """Standard Metaphone (Lawrence Philips / Gary Parker reference port)."""
    s = re.sub(r"[^a-z]", "", (word or "").lower())
    if not s:
        return ""

    # Drop duplicate adjacent letters, except 'c'.
    dedup = s[0]
    for ch in s[1:]:
        if ch != dedup[-1] or dedup[-1] == "c":
            dedup += ch
    s = dedup
    n = len(s)

    result: list[str] = []
    i = 0

    # Initial-letter exceptions.
    if s[:2] in ("kn", "gn", "pn", "ae", "wr"):
        i = 1
    elif s[0] == "x":
        result.append("s")
        i = 1
    elif s[:2] == "wh":
        result.append("w")
        i = 2

    while i < n:
        c = s[i]
        if _is_vowel(c):
            if i == 0:
                result.append(c)
            i += 1
        elif c == "b":
            if not (i > 0 and i == n - 1 and s[i - 1] == "m"):
                result.append("b")
            i += 1
        elif c == "c":
            if i + 1 < n and s[i + 1] == "h":
                if i == 0 and i + 2 < n and not _is_vowel(s[i + 2]):
                    result.append("k")
                else:
                    result.append("x")
                i += 2
            elif i + 1 < n and s[i + 1] == "i" and i + 2 < n and s[i + 2] in "ao":
                result.append("s")
                i += 3
            elif i + 1 < n and s[i + 1] in "eiy":
                result.append("s")
                i += 2
            else:
                result.append("k")
                i += 1
        elif c == "d":
            if i + 2 < n and s[i + 1] == "g" and s[i + 2] in "eiy":
                result.append("j")
                i += 3
            else:
                result.append("t")
                i += 1
        elif c == "g":
            if i + 1 < n and s[i + 1] == "h":
                if i == 0 or (i > 0 and not _is_vowel(s[i - 1])):
                    result.append("f")
                i += 2
            elif i + 1 < n and s[i + 1] == "n":
                if i == n - 2 or (i + 2 < n and not _is_vowel(s[i + 2])):
                    i += 2  # silent g
                else:
                    result.append("k")
                    result.append("n")
                    i += 2
            elif i + 1 < n and s[i + 1] in "eiy":
                result.append("j")
                i += 2
            else:
                result.append("k")
                i += 1
        elif c == "h":
            if i > 0 and _is_vowel(s[i - 1]) and (i + 1 >= n or not _is_vowel(s[i + 1])):
                i += 1  # silent h
            else:
                result.append("h")
                i += 1
        elif c == "k":
            if i > 0 and s[i - 1] == "c":
                i += 1  # already encoded by 'c'
            else:
                result.append("k")
                i += 1
        elif c == "p":
            if i + 1 < n and s[i + 1] == "h":
                result.append("f")
                i += 2
            else:
                result.append("p")
                i += 1
        elif c == "q":
            result.append("k")
            i += 1
        elif c == "s":
            if i + 1 < n and s[i + 1] == "h":
                result.append("x")
                i += 2
            elif i + 2 < n and s[i + 1] == "i" and s[i + 2] in "oa":
                result.append("x")
                i += 3
            else:
                result.append("s")
                i += 1
        elif c == "t":
            if i + 1 < n and s[i + 1] == "h":
                result.append("0")
                i += 2
            elif i + 2 < n and s[i + 1] == "i" and s[i + 2] in "oa":
                result.append("x")
                i += 3
            else:
                result.append("t")
                i += 1
        elif c == "v":
            result.append("f")
            i += 1
        elif c == "x":
            result.append("k")
            result.append("s")
            i += 1
        elif c == "y":
            if i > 0 and _is_vowel(s[i - 1]):
                i += 1  # silent y
            else:
                result.append("y")
                i += 1
        elif c == "z":
            result.append("s")
            i += 1
        else:  # f j l m n r w (and any unhandled consonant)
            result.append(c)
            i += 1

    return "".join(result).upper()


def _jaro_winkler_fallback(a: str, b: str, prefix_weight: float = 0.1) -> float:
    """Standard Jaro-Winkler similarity."""
    s1 = (a or "").lower()
    s2 = (b or "").lower()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    match_dist = max(len1, len2) // 2 - 1
    if match_dist < 0:
        match_dist = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0

    for i in range(len1):
        start = max(0, i - match_dist)
        end = min(i + match_dist + 1, len2)
        for j in range(start, end):
            if not s2_matches[j] and s1[i] == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    transpositions = 0
    k = 0
    for i in range(len1):
        if s1_matches[i]:
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
    transpositions //= 2

    jaro = (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3.0

    prefix = 0
    for x, y in zip(s1, s2):
        if x != y or prefix >= 4:
            break
        prefix += 1

    return jaro + prefix * prefix_weight * (1.0 - jaro)
