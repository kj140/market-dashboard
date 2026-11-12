"""Retrying HTTP GET shared by the fetchers."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


def get_with_retry(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 30,
    retries: int = 2,
    backoff: float = 2.0,
) -> requests.Response:
    """GET with retries; raises the last exception if every attempt fails.

    Only the exception type is logged: messages may contain the full URL
    (and therefore API keys passed in params).
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("GET attempt %d/%d failed: %s", attempt + 1, retries + 1, type(exc).__name__)
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc
