"""Shared networking helpers."""

from __future__ import annotations

import ssl
from functools import lru_cache

__all__ = ["ssl_context"]


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """TLS context backed by the operating system's trust store.

    httpx defaults to the bundled ``certifi`` roots, which fail with
    ``CERTIFICATE_VERIFY_FAILED`` on machines whose antivirus / corporate proxy
    re-signs HTTPS traffic with a locally-installed root. The stdlib default
    context loads the OS store (the Windows cert store on Windows), so it
    trusts whatever the browser trusts.
    """
    ctx = ssl.create_default_context()
    try:  # also trust certifi's roots when available, for minimal Linux images
        import certifi

        ctx.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001 - optional extra roots
        pass
    return ctx
