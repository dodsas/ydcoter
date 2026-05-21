"""Thin client for the yclaude HTTP gateway (Claude CLI behind FastAPI).

Flow:
    1. POST /auth/token  with master API_KEY  -> JWT (cached in-process)
    2. POST /chat        with `Authorization: Bearer <JWT>`

The JWT is reused until ~30s before its declared expiry, at which point
the next call transparently refreshes it. On 401 we also force a refresh
once before giving up.

Errors are raised as :class:`YClaudeError` with a single ``status_code``
field so the FastAPI layer can translate them into HTTP responses.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings, get_settings


class YClaudeError(RuntimeError):
    """Raised when the yclaude gateway returns a non-2xx response we can't
    recover from. ``status_code`` is meant to be surfaced to the HTTP
    layer (e.g. 502 for upstream failure)."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Token:
    value: str
    expires_at: float  # epoch seconds


class YClaudeClient:
    """Stateful client that caches a JWT across requests.

    Thread-safe by way of a single lock around the refresh path. The lock
    is only held while doing the token exchange itself, not while making
    /chat calls.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._token: Optional[_Token] = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._settings.yclaude_enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, question: str, *, model: Optional[str] = None) -> str:
        """Send a question to /chat and return the plain-text answer."""
        if not self.enabled:
            raise YClaudeError(
                "yclaude is not configured — set YCLAUDE_BASE_URL and YCLAUDE_API_KEY",
                status_code=503,
            )

        body: dict = {"question": question}
        chosen_model = model or self._settings.yclaude_model
        if chosen_model:
            body["model"] = chosen_model

        # First attempt with the cached/freshly-fetched token. If we hit
        # 401 (e.g. server restarted with a new JWT_SECRET, JWT really
        # expired between our check and the call) we refresh once.
        for attempt in (1, 2):
            token = self._get_token(force_refresh=(attempt == 2))
            try:
                with httpx.Client(timeout=self._settings.yclaude_timeout) as client:
                    resp = client.post(
                        f"{self._settings.yclaude_base_url}/chat",
                        headers={"Authorization": f"Bearer {token}"},
                        json=body,
                    )
            except httpx.HTTPError as exc:
                raise YClaudeError(f"yclaude request failed: {exc}", status_code=502) from exc

            if resp.status_code == 401 and attempt == 1:
                continue  # refresh + retry
            if resp.status_code >= 400:
                raise YClaudeError(
                    f"yclaude /chat returned {resp.status_code}: {resp.text[:300]}",
                    status_code=502,
                )

            payload = _safe_json(resp)
            answer = payload.get("answer")
            if not isinstance(answer, str):
                raise YClaudeError(
                    f"yclaude /chat response missing 'answer': {payload!r}",
                    status_code=502,
                )
            return answer

        # Unreachable — the loop returns or raises on every path.
        raise YClaudeError("yclaude /chat: out of retries", status_code=502)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _get_token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._token is not None
                and self._token.expires_at - now > 30
            ):
                return self._token.value

            try:
                with httpx.Client(timeout=self._settings.yclaude_timeout) as client:
                    resp = client.post(
                        f"{self._settings.yclaude_base_url}/auth/token",
                        json={
                            "api_key": self._settings.yclaude_api_key,
                            "client_id": self._settings.yclaude_client_id,
                        },
                    )
            except httpx.HTTPError as exc:
                raise YClaudeError(
                    f"yclaude auth request failed: {exc}", status_code=502,
                ) from exc

            if resp.status_code == 401:
                raise YClaudeError(
                    "yclaude rejected API key — check YCLAUDE_API_KEY",
                    status_code=401,
                )
            if resp.status_code >= 400:
                raise YClaudeError(
                    f"yclaude /auth/token returned {resp.status_code}: {resp.text[:300]}",
                    status_code=502,
                )

            payload = _safe_json(resp)
            token = payload.get("access_token")
            expires_in = payload.get("expires_in", 3600)
            if not isinstance(token, str) or not token:
                raise YClaudeError(
                    f"yclaude /auth/token response missing 'access_token': {payload!r}",
                    status_code=502,
                )

            self._token = _Token(value=token, expires_at=now + float(expires_in))
            return token


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError as exc:
        raise YClaudeError(
            f"yclaude returned non-JSON ({resp.status_code}): {resp.text[:300]}",
            status_code=502,
        ) from exc
    if not isinstance(data, dict):
        raise YClaudeError(
            f"yclaude returned non-object JSON: {data!r}", status_code=502,
        )
    return data


# Module-level singleton — FastAPI imports this directly. Reinstantiate
# only in tests via ``YClaudeClient(custom_settings)``.
client = YClaudeClient()
