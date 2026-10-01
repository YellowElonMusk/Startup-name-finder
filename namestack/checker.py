"""Async domain availability checking.

Lookup chain per domain, stopping at the first definitive answer:

0. DNS: a name that resolves is certainly registered (skipped for TLDs with
   wildcard DNS). This spares the registries most of the traffic.
1. RDAP at the TLD's own registry (from the IANA bootstrap file). Aggregators
   like rdap.org answer 404 for TLDs without RDAP (e.g. ``.io``), which would
   make every such domain look AVAILABLE, so we never use them.
2. WHOIS at the registry's port-43 server (discovered via whois.iana.org).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import socket
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Iterable, Optional

import httpx

from .net import ssl_context

__all__ = ["Status", "CheckResult", "AvailabilityChecker"]

IANA_RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
IANA_WHOIS = "whois.iana.org"

# Working RDAP servers for TLDs missing from the IANA bootstrap file.
# (Verified: correct 404/200 answers, tolerant of bursts - unlike their
# port-43 WHOIS, which refuses parallel connections.)
RDAP_SUPPLEMENT: dict[str, str] = {
    "io": "https://rdap.identitydigital.services/rdap/",
    "sh": "https://rdap.identitydigital.services/rdap/",
    "ac": "https://rdap.identitydigital.services/rdap/",
}

# TLD -> authoritative WHOIS host; fallback is "{tld}.whois-servers.net".
WHOIS_SERVERS: dict[str, str] = {
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.publicinterestregistry.org",
    "io": "whois.nic.io",
    "ai": "whois.nic.ai",
    "co": "whois.registry.co",
    "xyz": "whois.nic.xyz",
    "tech": "whois.nic.tech",
    "me": "whois.nic.me",
    "tv": "whois.nic.tv",
    "cc": "ccwhois.verisign-grs.com",
    "sh": "whois.nic.sh",
    "gg": "whois.gg",
    "so": "whois.nic.so",
    "fm": "whois.nic.fm",
    "am": "whois.amnic.net",
    "us": "whois.nic.us",
    "es": "whois.nic.es",
    "it": "whois.nic.it",
    "is": "whois.isnic.is",
    "im": "whois.nic.im",
    "in": "whois.registry.in",
    "de": "whois.denic.de",
    "ly": "whois.nic.ly",
    "fi": "whois.fi",
}

_NOT_FOUND = re.compile(
    r"no match|not found|no entries? found|no data found|domain not found|"
    r"status:\s*free|status:\s*available|no object found|nothing found|"
    r"no matching record|available for registration|queried object does not exist|"
    r"not registered|no registration|domain status:\s*free|no whois data|"
    r"does not exist|not exist|no matching",
    re.IGNORECASE,
)

_WHOIS_THROTTLED = re.compile(
    r"limit exceeded|rate limit|too many (requests|queries)|query rate|"
    r"try again later|access denied|exceeded the maximum",
    re.IGNORECASE,
)

# Process-wide caches: tld -> RDAP base URL / WHOIS host (None = none exists).
_rdap_bases: Optional[dict[str, str]] = None
_rdap_lock: Optional[asyncio.Lock] = None
_whois_hosts: dict[str, Optional[str]] = dict(WHOIS_SERVERS)
_dns_ok: dict[str, bool] = {}  # tld -> no wildcard DNS
_rdap_blocked_until: dict[str, float] = {}  # rdap base -> monotonic time

# Measured sustained limits (seconds between requests, max parallel) for
# registries that throttle hard. Others start fast and adapt.
_KNOWN_PACE: dict[str, tuple[float, int]] = {
    "pubapi.registry.google": (1.0, 2),   # .dev .app .page ...: ~1 req/s, burst ~12
}


class Status(str, Enum):
    AVAILABLE = "AVAILABLE"
    REGISTERED = "REGISTERED"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CheckResult:
    domain: str
    status: Status
    source: str = ""
    detail: str = ""
    latency_ms: int = 0


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _dry_run(domain: str) -> CheckResult:
    """Deterministic, network-free result for testing and demos."""
    v = hashlib.md5(domain.encode("utf-8")).digest()[0]
    if v < 90:
        status = Status.AVAILABLE
    elif v < 245:
        status = Status.REGISTERED
    elif v < 250:
        status = Status.RATE_LIMITED
    else:
        status = Status.UNKNOWN
    return CheckResult(domain, status, "dry-run", "simulated", 1)


@dataclass
class _Pace:
    interval: float
    sem: asyncio.Semaphore
    floor: float = 0.0
    next_allowed: float = 0.0


class AvailabilityChecker:
    """Checks many domains in parallel with RDAP, falling back to WHOIS.

    Overall concurrency is bounded by a semaphore. Each registry host gets its
    own adaptive pacing and connection cap, so one slow or rate-limiting
    registry (typically a ccTLD WHOIS server) doesn't hold back the others.
    """

    def __init__(
        self,
        concurrency: int = 20,
        timeout: float = 10.0,
        retries: int = 2,
        base_interval: float = 0.05,
        max_interval: float = 2.0,
        dry_run: bool = False,
    ) -> None:
        self.concurrency = max(1, concurrency)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.dry_run = dry_run
        self._base_interval = base_interval
        self._max_interval = max_interval
        self._paces: dict[str, _Pace] = {}
        self._net_sem: Optional[asyncio.Semaphore] = None
        self._dns_probes: dict[str, asyncio.Task] = {}

    @property
    def _net(self) -> asyncio.Semaphore:
        """Global cap on in-flight network operations (created inside the loop)."""
        if self._net_sem is None:
            self._net_sem = asyncio.Semaphore(self.concurrency)
        return self._net_sem

    # -- adaptive per-host pacing -----------------------------------------
    def _pace(self, key: str) -> "_Pace":
        pace = self._paces.get(key)
        if pace is None:
            # WHOIS servers commonly allow only a few parallel connections per IP.
            interval, cap = self._base_interval, (2 if key.startswith("whois:") else 10)
            for host, known in _KNOWN_PACE.items():
                if host in key:
                    interval, cap = known
            pace = self._paces[key] = _Pace(interval, asyncio.Semaphore(cap), floor=interval)
        return pace

    async def _throttle(self, key: str) -> None:
        """Reserve the next send slot for *key* and wait for it (lock-free)."""
        pace = self._pace(key)
        now = time.monotonic()
        slot = max(now, pace.next_allowed)
        pace.next_allowed = slot + pace.interval
        if slot > now:
            await asyncio.sleep(slot - now)

    def _backoff(self, key: str) -> None:
        pace = self._pace(key)
        pace.interval = min(self._max_interval, max(0.25, pace.interval * 2))
        pace.next_allowed = max(pace.next_allowed, time.monotonic() + 1.0)

    def _relax(self, key: str) -> None:
        pace = self._pace(key)
        pace.interval = max(pace.floor, 0.01, pace.interval * 0.97)

    # -- single-domain checks ---------------------------------------------
    async def _rdap_base(self, tld: str, client: httpx.AsyncClient) -> Optional[str]:
        global _rdap_bases, _rdap_lock
        if _rdap_bases is None:
            if _rdap_lock is None:
                _rdap_lock = asyncio.Lock()
            async with _rdap_lock:
                if _rdap_bases is None:
                    bases: dict[str, str] = {}
                    try:
                        resp = await client.get(IANA_RDAP_BOOTSTRAP)
                        resp.raise_for_status()
                        for tlds, urls in resp.json().get("services", []):
                            url = next((u for u in urls if u.startswith("https")), urls[0])
                            for t in tlds:
                                bases[t.lower()] = url.rstrip("/") + "/"
                    except (httpx.HTTPError, ValueError):
                        pass  # no bootstrap -> everything goes through WHOIS
                    for t, url in RDAP_SUPPLEMENT.items():
                        bases.setdefault(t, url)
                    _rdap_bases = bases
        return _rdap_bases.get(tld)

    async def _rdap(
        self, domain: str, base: str, client: httpx.AsyncClient
    ) -> tuple[Status, str, str]:
        resp = await client.get(f"{base}domain/{domain}")
        code = resp.status_code
        if code == 404:
            return Status.AVAILABLE, "rdap", "rdap 404"
        if code == 200:
            return Status.REGISTERED, "rdap", "rdap 200"
        if code in (429, 503):
            retry_after = resp.headers.get("retry-after", "")
            if retry_after.isdigit() and int(retry_after) > 20:
                # Circuit breaker: the registry wants us gone for a while
                # (Identity Digital answers with ~24h). Use WHOIS until then.
                _rdap_blocked_until[base] = time.monotonic() + int(retry_after)
            return Status.RATE_LIMITED, "rdap", f"rdap {code}"
        return Status.UNKNOWN, "rdap", f"rdap {code}"

    async def _whois_query(self, host: str, query: str) -> str:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 43), timeout=self.timeout
        )
        try:
            writer.write(f"{query}\r\n".encode("ascii", "ignore"))
            await writer.drain()
            data = await asyncio.wait_for(reader.read(-1), timeout=self.timeout)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        return data.decode("utf-8", "ignore")

    async def _whois_host(self, tld: str) -> Optional[str]:
        if tld not in _whois_hosts:
            host = None
            with contextlib.suppress(asyncio.TimeoutError, OSError):
                text = await self._whois_query(IANA_WHOIS, tld)
                m = re.search(r"^whois:[ \t]*(\S+)", text, re.IGNORECASE | re.MULTILINE)
                host = m.group(1) if m else None
            _whois_hosts[tld] = host
        return _whois_hosts[tld]

    async def _whois(self, domain: str) -> tuple[Status, str, str]:
        tld = domain.rsplit(".", 1)[-1].lower()
        host = await self._whois_host(tld)
        if not host:
            return Status.UNKNOWN, "whois", f"no whois server for .{tld}"
        try:
            text = await self._whois_query(host, domain)
        except socket.gaierror:
            # Registry moved its WHOIS host: forget it and ask IANA once.
            if _whois_hosts.get(tld) == host:
                del _whois_hosts[tld]
            host = await self._whois_host(tld)
            if not host:
                return Status.UNKNOWN, "whois", f"no whois server for .{tld}"
            text = await self._whois_query(host, domain)
        if not text.strip():
            return Status.UNKNOWN, "whois", "empty response"
        if _WHOIS_THROTTLED.search(text[:600]):
            return Status.RATE_LIMITED, "whois", "whois throttled"
        if _NOT_FOUND.search(text):
            return Status.AVAILABLE, "whois", "not-found"
        return Status.REGISTERED, "whois", "record found"

    async def _resolves(self, domain: str) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.getaddrinfo(domain, None), timeout=4)
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    async def _dns_trustworthy(self, tld: str) -> bool:
        """False for TLDs with wildcard DNS, where every name 'resolves'."""
        if tld not in _dns_ok:
            task = self._dns_probes.get(tld)
            if task is None:
                probe = f"nx-{uuid.uuid4().hex[:16]}-namestack.{tld}"
                task = self._dns_probes[tld] = asyncio.ensure_future(self._resolves(probe))
            _dns_ok[tld] = not await task
        return _dns_ok[tld]

    async def _io(self, key: str):
        """Per-host cap + pacing, then a global slot only for the actual I/O."""
        pace = self._pace(key)
        await pace.sem.acquire()
        try:
            await self._throttle(key)
        except BaseException:
            pace.sem.release()
            raise
        await self._net.acquire()
        return pace

    def _io_done(self, pace: "_Pace") -> None:
        self._net.release()
        pace.sem.release()

    async def check(self, domain: str, client: httpx.AsyncClient) -> CheckResult:
        if self.dry_run:
            return _dry_run(domain)

        start = time.monotonic()
        tld = domain.rsplit(".", 1)[-1].lower()

        # A name that resolves is certainly registered: skip the registry.
        if await self._dns_trustworthy(tld):
            async with self._net:
                resolves = await self._resolves(domain)
            if resolves:
                return CheckResult(domain, Status.REGISTERED, "dns", "resolves", _ms(start))

        base = await self._rdap_base(tld, client)
        rdap_key, whois_key = f"rdap:{base}", f"whois:{tld}"
        backoff = 0.5
        last_detail = ""
        failures = throttled = 0
        # Rate-limit responses get their own, larger budget: they mean "later",
        # not "broken", and slow registries (e.g. Google's .dev/.app) recover
        # within seconds.
        has_whois = bool(await self._whois_host(tld))
        while failures <= self.retries and throttled <= 8:
            rdap_throttled = False
            if base and time.monotonic() >= _rdap_blocked_until.get(base, 0.0):
                pace = await self._io(rdap_key)
                try:
                    status, source, detail = await self._rdap(domain, base, client)
                except httpx.HTTPError as exc:
                    status, source, detail = Status.UNKNOWN, "rdap", f"rdap {type(exc).__name__}"
                finally:
                    self._io_done(pace)
                if status in (Status.AVAILABLE, Status.REGISTERED):
                    self._relax(rdap_key)
                    return CheckResult(domain, status, source, detail, _ms(start))
                last_detail = detail
                if status is Status.RATE_LIMITED:
                    self._backoff(rdap_key)
                    rdap_throttled = True

            # RDAP missing, blocked, throttled or inconclusive -> WHOIS.
            whois_throttled = False
            if has_whois:
                pace = await self._io(whois_key)
                try:
                    status, source, detail = await self._whois(domain)
                except (ConnectionRefusedError, ConnectionResetError) as exc:
                    # Busy WHOIS servers refuse/reset instead of answering.
                    status, source, detail = Status.RATE_LIMITED, "whois", f"whois {type(exc).__name__}"
                except (asyncio.TimeoutError, OSError) as exc:
                    status, source, detail = Status.UNKNOWN, "whois", f"whois {type(exc).__name__}"
                finally:
                    self._io_done(pace)
                if status in (Status.AVAILABLE, Status.REGISTERED):
                    self._relax(whois_key)
                    return CheckResult(domain, status, source, detail, _ms(start))
                last_detail = detail
                if status is Status.RATE_LIMITED:
                    self._backoff(whois_key)
                    whois_throttled = True
            elif not base:
                last_detail = f"no rdap or whois server for .{tld}"
                break

            if (rdap_throttled or not base) and (whois_throttled or not has_whois):
                # Every source for this TLD says "later": wait, don't count a failure.
                throttled += 1
                await asyncio.sleep(min(8.0, 1.0 * throttled))
                continue
            failures += 1
            await asyncio.sleep(backoff)
            backoff *= 2

        return CheckResult(domain, Status.UNKNOWN, "none", last_detail, _ms(start))

    async def check_many(
        self,
        domains: Iterable[str],
        on_result: Optional[Callable[[CheckResult], Awaitable[None]]] = None,
    ) -> list[CheckResult]:
        """Check every domain in parallel; invoke *on_result* as each finishes."""
        domain_list = list(domains)
        headers = {"User-Agent": "namestack/0.1 (+https://github.com/namestack)"}
        limits = httpx.Limits(max_connections=self.concurrency, max_keepalive_connections=self.concurrency)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
            verify=ssl_context(),
            limits=limits,
        ) as client:

            async def worker(domain: str) -> CheckResult:
                result = await self.check(domain, client)
                if on_result is not None:
                    await on_result(result)
                return result

            return await asyncio.gather(*(worker(d) for d in domain_list))
