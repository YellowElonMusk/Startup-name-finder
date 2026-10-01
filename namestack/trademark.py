"""Lightweight USPTO wordmark collision screening.

Queries the (undocumented but public) search API behind the USPTO trademark
search web app. It is best-effort: failures degrade to UNKNOWN and never block
the rest of the pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Iterable, Optional

import httpx

from .net import ssl_context
from .phonetics import metaphone

__all__ = ["TrademarkRisk", "TrademarkResult", "check_word", "check_words"]

TM_BASE = "https://tmsearch.uspto.gov"
TM_PATHS = ("/prod-stage-v1-0-0/tmsearch", "/api-v1-0-0/tmsearch")


class TrademarkRisk(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass
class TrademarkResult:
    word: str
    risk: TrademarkRisk
    total_hits: int = 0
    exact_match: bool = False
    detail: str = ""


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (word or "").lower())


def _classify(word: str, payload: dict) -> TrademarkResult:
    """Classify a USPTO search envelope into a risk level."""
    hits_obj = payload.get("hits") or {}
    hits = hits_obj.get("hits") or []
    total = hits_obj.get("totalValue")
    if total is None:
        total_obj = hits_obj.get("total")
        total = total_obj.get("value", 0) if isinstance(total_obj, dict) else total_obj
    try:
        total = int(total or 0)
    except (TypeError, ValueError):
        total = 0

    norm = _norm(word)
    exact = False
    for hit in hits:
        src = hit.get("source") or hit.get("_source") or hit
        wm = src.get("wordmark") or src.get("markVerbalElementText") or ""
        if _norm(wm) == norm:
            exact = True
            break

    if exact:
        return TrademarkResult(word, TrademarkRisk.HIGH, total, True, "exact wordmark")
    if total > 0:
        # High-risk phonetic near-miss among returned hits.
        key = metaphone(norm)
        for hit in hits:
            src = hit.get("source") or hit.get("_source") or hit
            wm = src.get("wordmark") or src.get("markVerbalElementText") or ""
            if key and metaphone(_norm(wm)) == key:
                return TrademarkResult(
                    word, TrademarkRisk.MEDIUM, total, False, "phonetic near-match"
                )
        return TrademarkResult(word, TrademarkRisk.LOW, total, False, f"{total} related marks")
    return TrademarkResult(word, TrademarkRisk.NONE, 0, False, "no hits")


def _dry_run_tm(word: str) -> TrademarkResult:
    v = hashlib.md5(word.encode("utf-8")).digest()[0]
    if v < 150:
        risk = TrademarkRisk.NONE
    elif v < 215:
        risk = TrademarkRisk.LOW
    elif v < 235:
        risk = TrademarkRisk.MEDIUM
    elif v < 245:
        risk = TrademarkRisk.HIGH
    else:
        risk = TrademarkRisk.UNKNOWN
    return TrademarkResult(word, risk, detail="simulated")


async def check_word(
    client: httpx.AsyncClient, word: str, dry_run: bool = False
) -> TrademarkResult:
    """Screen a single wordmark against USPTO."""
    if dry_run:
        return _dry_run_tm(word)

    body = {
        "query": {"bool": {"must": [{"match": {"wordmark": word}}]}},
        "from": 0,
        "size": 25,
        "track_total_hits": True,
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": TM_BASE,
        "Referer": TM_BASE + "/",
        "User-Agent": "namestack/0.1",
    }
    for path in TM_PATHS:
        url = TM_BASE + path
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 404:
            continue
        if resp.status_code in (202, 403):
            return TrademarkResult(word, TrademarkRisk.UNKNOWN, detail=f"WAF {resp.status_code}")
        if resp.status_code == 429:
            return TrademarkResult(word, TrademarkRisk.UNKNOWN, detail="rate-limited")
        if resp.status_code >= 400:
            return TrademarkResult(word, TrademarkRisk.UNKNOWN, detail=f"http {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError:
            return TrademarkResult(word, TrademarkRisk.UNKNOWN, detail="non-JSON response")
        return _classify(word, payload)

    return TrademarkResult(word, TrademarkRisk.UNKNOWN, detail="no endpoint")


async def check_words(
    words: Iterable[str],
    concurrency: int = 5,
    dry_run: bool = False,
    on_result: Optional[Callable[[TrademarkResult], Awaitable[None]]] = None,
) -> list[TrademarkResult]:
    """Screen many wordmarks with bounded concurrency."""
    word_list = list(dict.fromkeys(words))
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": "namestack/0.1"},
        verify=ssl_context(),
    ) as client:

        async def worker(word: str) -> TrademarkResult:
            async with sem:
                result = await check_word(client, word, dry_run=dry_run)
                if on_result is not None:
                    await on_result(result)
                return result

        return await asyncio.gather(*(worker(w) for w in word_list))
