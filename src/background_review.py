"""Background/resumable GPT-6 Astra response transport.

This module never retries generation. It persists the server response ID so a
caller can retrieve the same paid response instead of creating a replacement.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import requests


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "incomplete"}
PENDING_STATUSES = {"queued", "in_progress"}


class ResponseTransportError(RuntimeError):
    """Transport/protocol error without exposing response bodies or secrets."""


@dataclass
class PollResult:
    response: dict
    terminal: bool


class BackgroundResponses:
    def __init__(self, api_key: str, *, session=None, connect_timeout=10, read_timeout=30):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is missing.")
        self.api_key = api_key
        self.session = session or requests.Session()
        self._owns = session is None
        self.timeout = (connect_timeout, read_timeout)
        self.base = "https://api.openai.com/v1"

    @property
    def headers(self):
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }

    def close(self):
        if self._owns:
            self.session.close()

    def _json(self, response):
        if response.status_code < 200 or response.status_code >= 300:
            request_id = response.headers.get("x-request-id")
            raise ResponseTransportError(
                f"OpenAI HTTP {response.status_code}; request_id={request_id or 'unknown'}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise ResponseTransportError("OpenAI returned non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise ResponseTransportError("OpenAI returned an invalid response object.")
        return payload

    def create(self, spec: dict) -> dict:
        body = dict(spec)
        body["background"] = True
        # store=False minimizes retention; background responses remain temporarily
        # retrievable for polling according to OpenAI's background-mode docs.
        body["store"] = False
        try:
            response = self.session.post(
                self.base + "/responses",
                headers=self.headers,
                json=body,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ResponseTransportError(type(exc).__name__) from exc
        payload = self._json(response)
        if not isinstance(payload.get("id"), str) or not payload["id"]:
            raise ResponseTransportError("Background create returned no response id.")
        if payload.get("status") not in PENDING_STATUSES | TERMINAL_STATUSES:
            raise ResponseTransportError("Background create returned unknown status.")
        return payload

    def retrieve(self, response_id: str) -> dict:
        if not response_id or not isinstance(response_id, str):
            raise ValueError("response_id is required.")
        try:
            response = self.session.get(
                self.base + "/responses/" + response_id,
                headers={"Authorization": "Bearer " + self.api_key},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ResponseTransportError(type(exc).__name__) from exc
        payload = self._json(response)
        if payload.get("id") != response_id:
            raise ResponseTransportError("Retrieved response id did not match the requested id.")
        return payload

    def cancel(self, response_id: str) -> dict:
        if not response_id or not isinstance(response_id, str):
            raise ValueError("response_id is required.")
        try:
            response = self.session.post(
                self.base + "/responses/" + response_id + "/cancel",
                headers=self.headers,
                json={},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ResponseTransportError(type(exc).__name__) from exc
        return self._json(response)

    def poll(
        self,
        response_id: str,
        *,
        max_wait_seconds: int = 120,
        interval_seconds: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> PollResult:
        if max_wait_seconds < 0 or interval_seconds < 1:
            raise ValueError("Invalid polling interval/window.")
        deadline = time.monotonic() + max_wait_seconds
        while True:
            payload = self.retrieve(response_id)
            status = payload.get("status")
            if status in TERMINAL_STATUSES:
                return PollResult(payload, True)
            if status not in PENDING_STATUSES:
                raise ResponseTransportError(f"Unknown response status: {status}")
            if time.monotonic() >= deadline:
                return PollResult(payload, False)
            sleep(interval_seconds)
