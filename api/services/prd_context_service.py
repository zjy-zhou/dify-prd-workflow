"""Wiki PRD context access facade.

This service is the only layer in the PRD compiler path that knows how to call
the external Wiki Tree Context API. It returns a normalized
``PrdWikiContext`` and raises readable service errors; it never reads or writes
Dify workflow drafts.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from configs import dify_config
from core.helper import ssrf_proxy
from core.workflow.prd_compiler.entities import WikiTreeContextSource
from core.workflow.prd_compiler.wiki_context import (
    PrdWikiContext,
    WikiContextNormalizationError,
    normalize_wiki_tree_context_response,
)

logger = logging.getLogger(__name__)

WIKI_TREE_CONTEXT_PATH = "/api/wiki/tree/context"


class WikiContextHttpPost(Protocol):
    def __call__(self, url: str, **kwargs: Any) -> httpx.Response: ...


class PrdContextServiceError(RuntimeError):
    """Raised when Wiki context cannot be resolved into compiler input."""

    code: str

    def __init__(self, message: str, *, code: str = "wiki_context_error") -> None:
        super().__init__(message)
        self.code = code


class PrdContextService:
    """Fetches and normalizes PRD context from supported sources."""

    _base_url: str
    _timeout_seconds: float
    _http_post: WikiContextHttpPost

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        http_post: WikiContextHttpPost | None = None,
    ) -> None:
        self._base_url = (base_url if base_url is not None else dify_config.PRD_WIKI_TREE_CONTEXT_BASE_URL).strip()
        self._timeout_seconds = timeout_seconds or float(dify_config.PRD_WIKI_TREE_CONTEXT_TIMEOUT)
        self._http_post = http_post or ssrf_proxy.post

    def fetch_wiki_tree_context(self, source: WikiTreeContextSource) -> PrdWikiContext:
        """Call Wiki Tree Context API and return normalized compiler input.

        Args:
            source: Wiki source descriptor from the public PRD generation API.

        Raises:
            PrdContextServiceError: For missing config, transport failures,
                HTTP errors, Wiki business errors, malformed JSON, or malformed
                context payloads.
        """
        if not self._base_url:
            raise PrdContextServiceError(
                "Wiki Tree Context API base URL is not configured.",
                code="wiki_context_not_configured",
            )

        url = f"{self._base_url.rstrip('/')}{WIKI_TREE_CONTEXT_PATH}"
        request_body = {
            "doc_id": source.doc_id,
            "tree_type": source.tree_type,
            "force_rebuild": source.force_rebuild,
        }
        headers = {
            "Content-Type": "application/json",
            "LIGHTRAG-WORKSPACE": source.workspace,
        }

        try:
            response = self._http_post(
                url,
                headers=headers,
                json=request_body,
                timeout=httpx.Timeout(self._timeout_seconds),
                max_retries=0,
            )
        except httpx.TimeoutException as exc:
            raise PrdContextServiceError(
                f"Wiki Tree Context API request timed out after {self._timeout_seconds:g}s.",
                code="wiki_context_timeout",
            ) from exc
        except ssrf_proxy.max_retries_exceeded_error as exc:
            raise PrdContextServiceError(
                "Wiki Tree Context API request failed after retry limit.",
                code="wiki_context_retry_exceeded",
            ) from exc
        except ssrf_proxy.request_error as exc:
            raise PrdContextServiceError(
                f"Wiki Tree Context API request failed: {exc}",
                code="wiki_context_request_failed",
            ) from exc

        payload = self._decode_response(response, workspace=source.workspace)
        try:
            return normalize_wiki_tree_context_response(
                payload,
                doc_id=source.doc_id,
                workspace=source.workspace,
                tree_type=source.tree_type,
            )
        except WikiContextNormalizationError as exc:
            raise PrdContextServiceError(str(exc), code="wiki_context_invalid_response") from exc

    def _decode_response(self, response: httpx.Response, *, workspace: str) -> dict[str, Any]:
        if response.status_code in (401, 403):
            raise PrdContextServiceError(
                f"Wiki Tree Context API denied access for workspace {workspace} (HTTP {response.status_code}).",
                code="wiki_context_forbidden",
            )

        if response.status_code >= 500:
            raise PrdContextServiceError(
                f"Wiki Tree Context API returned HTTP {response.status_code}: {_response_detail(response)}",
                code="wiki_context_server_error",
            )

        if response.status_code >= 400:
            raise PrdContextServiceError(
                f"Wiki Tree Context API returned HTTP {response.status_code}: {_response_detail(response)}",
                code="wiki_context_http_error",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PrdContextServiceError(
                "Wiki Tree Context API returned non-JSON response.",
                code="wiki_context_invalid_json",
            ) from exc

        if not isinstance(payload, dict):
            raise PrdContextServiceError(
                "Wiki Tree Context API returned a non-object JSON response.",
                code="wiki_context_invalid_json",
            )

        if payload.get("ok") is False or payload.get("status") == "error":
            raise PrdContextServiceError(
                f"Wiki Tree Context API returned error: {_payload_error_detail(payload)}",
                code="wiki_context_business_error",
            )

        return payload


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500] or "empty response"
    if isinstance(payload, dict):
        return _payload_error_detail(payload)
    return str(payload)[:500]


def _payload_error_detail(payload: dict[str, Any]) -> str:
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:500]
    return "unknown error"
