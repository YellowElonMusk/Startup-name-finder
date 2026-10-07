"""Quick French name screening for the "French" naming style.

data.inpi.fr sits behind a Cloudflare browser challenge and INPI's own APIs
need an account, so the automatic check queries the free government company
search (recherche-entreprises.api.gouv.fr). It indexes the national company
register (RNE) that data.inpi.fr displays, and flags names already used by a
French company, its trade name or its shop sign. Each result also carries a
data.inpi.fr link so the user can confirm trademarks in one click.

Best-effort, like the USPTO screen: failures degrade to UNKNOWN.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Iterable, Optional
from urllib.parse import urlencode

import httpx

from .net import ssl_context

__all__ = ["FrStatus", "FrResult", "inpi_url", "check_name", "check_names"]

SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"

# Glued French heads ("lematin", "bellelune"): the register stores "LE MATIN",
# and its full-text search won't match the glued form, so also query it spaced.
_FR_HEADS = (
    "petite", "petit", "grande", "grand", "bonne", "belle", "beau", "bel", "bon",
    "mon", "les", "le", "la", "ma", "l",
)


class FrStatus(str, Enum):
    FREE = "FREE"          # no French company uses this exact name
    CLOSED = "CLOSED"      # only used by companies that have closed down
    TAKEN = "TAKEN"        # an active French company uses this exact name
    UNKNOWN = "UNKNOWN"


@dataclass
class FrResult:
    word: str
    status: FrStatus
    matches: int = 0
    company: str = ""      # example of a company using the name
    detail: str = ""

    @property
    def url(self) -> str:
        return inpi_url(self.word)


def inpi_url(word: str) -> str:
    """data.inpi.fr trademark search for *word* (opens in the user's browser)."""
    return "https://data.inpi.fr/search?" + urlencode({
        "advancedSearch": "{}", "displayStyle": "List", "filter": "{}",
        "nbResultsPerPage": 20, "order": "asc", "page": 1, "q": word,
        "sort": "relevance", "type": "brands",
    })


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _names_of(company: dict) -> Iterable[str]:
    """Every name a company trades under: legal name, acronym, trade names, signs."""
    yield company.get("nom_raison_sociale") or ""
    yield company.get("nom_complet") or ""
    yield company.get("sigle") or ""
    for etab in [company.get("siege") or {}, *(company.get("matching_etablissements") or [])]:
        yield etab.get("nom_commercial") or ""
        yield from etab.get("liste_enseignes") or []


def _classify(word: str, payload: dict) -> FrResult:
    norm = _norm(word)
    active, closed = [], []
    for company in payload.get("results") or []:
        if any(_norm(n) == norm for n in _names_of(company)):
            label = company.get("nom_complet") or company.get("nom_raison_sociale") or word
            (active if company.get("etat_administratif") == "A" else closed).append(label)
    if active:
        return FrResult(word, FrStatus.TAKEN, len(active), active[0], "active French company")
    if closed:
        return FrResult(word, FrStatus.CLOSED, len(closed), closed[0], "closed French company")
    return FrResult(word, FrStatus.FREE, 0, "", "no French company with this name")


def _queries(word: str) -> list[str]:
    queries = [word]
    for head in _FR_HEADS:
        if word.startswith(head) and len(word) - len(head) >= 3:
            queries.append(f"{head} {word[len(head):]}")
            break
    return queries


def _dry_run(word: str) -> FrResult:
    v = hashlib.md5(word.encode("utf-8")).digest()[1]
    status = FrStatus.FREE if v < 170 else FrStatus.CLOSED if v < 200 else FrStatus.TAKEN
    return FrResult(word, status, detail="simulated")


async def check_name(client: httpx.AsyncClient, word: str, dry_run: bool = False) -> FrResult:
    if dry_run:
        return _dry_run(word)
    companies: list[dict] = []
    for query in _queries(word):
        payload = await _search(client, query)
        if isinstance(payload, str):
            return FrResult(word, FrStatus.UNKNOWN, detail=payload)
        companies += payload.get("results") or []
    return _classify(word, {"results": companies})


async def _search(client: httpx.AsyncClient, query: str):
    """Register search payload, or a short error string."""
    for attempt in range(3):
        try:
            resp = await client.get(SEARCH_URL, params={"q": query, "per_page": 25})
        except httpx.HTTPError as exc:
            return type(exc).__name__
        if resp.status_code == 429:  # ~7 requests/s allowed; back off and retry
            await asyncio.sleep(1.0 + attempt)
            continue
        if resp.status_code >= 400:
            return f"http {resp.status_code}"
        try:
            return resp.json()
        except (ValueError, json.JSONDecodeError):
            return "non-JSON response"
    return "rate-limited"


async def check_names(
    words: Iterable[str],
    concurrency: int = 4,
    dry_run: bool = False,
    on_result: Optional[Callable[[FrResult], Awaitable[None]]] = None,
) -> list[FrResult]:
    """Screen many names against the French register with bounded concurrency."""
    word_list = list(dict.fromkeys(words))
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": "namestack/0.2"},
        verify=ssl_context(),
    ) as client:

        async def worker(word: str) -> FrResult:
            async with sem:
                result = await check_name(client, word, dry_run=dry_run)
                if on_result is not None:
                    await on_result(result)
                return result

        return await asyncio.gather(*(worker(w) for w in word_list))
