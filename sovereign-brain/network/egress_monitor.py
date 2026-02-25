"""
Sovereign Brain — Egress Monitor
=================================
Custom httpx transport that intercepts ALL outbound HTTP calls made
by the Anthropic SDK. Provides:

  Connected mode:  logs event_type="egress_request_sent" (severity=info)
                   then allows the call through to the real transport
  Airgapped mode:  logs event_type="egress_attempt_blocked" (severity=critical)
                   then raises EgressBlockedError — no socket is ever opened

Injected via:
    anthropic.AsyncAnthropic(http_client=httpx.AsyncClient(transport=EgressMonitorTransport(...)))

The on_egress callback is async and must never raise — logging failure
must not break the request path.
"""

import logging
from typing import Callable, Coroutine, Optional

import httpx

log = logging.getLogger("sovereign.egress")


class EgressBlockedError(Exception):
    """Raised when an outbound call is attempted while MODE=airgapped."""


class EgressMonitorTransport(httpx.AsyncBaseTransport):
    """
    Drop-in replacement for httpx.AsyncHTTPTransport.
    Intercepts every outbound request for audit logging and airgap enforcement.
    """

    def __init__(
        self,
        mode: str,
        on_egress: Optional[Callable[..., Coroutine]] = None,
    ):
        self._mode = mode
        self._on_egress = on_egress  # async (event_type, host, path, method, blocked) -> None
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        method = request.method
        blocked = self._mode == "airgapped"

        log.info(
            "EGRESS %s: %s %s%s",
            "BLOCKED" if blocked else "ALLOWED",
            method, host, path,
        )

        if self._on_egress:
            try:
                await self._on_egress(
                    event_type="egress_attempt_blocked" if blocked else "egress_request_sent",
                    host=host,
                    path=path,
                    method=method,
                    blocked=blocked,
                )
            except Exception:
                pass  # Never let logging failure break the request path

        if blocked:
            raise EgressBlockedError(
                f"Outbound call to {host}{path} blocked: MODE=airgapped"
            )

        return await self._inner.handle_async_request(request)

    async def aclose(self):
        await self._inner.aclose()
