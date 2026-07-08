from __future__ import annotations

from typing import Any

import httpx
import pytest

from core.workflow.prd_compiler.entities import WikiTreeContextSource
from services.prd_context_service import PrdContextService, PrdContextServiceError


def _source() -> WikiTreeContextSource:
    return WikiTreeContextSource.model_validate(
        {
            "type": "wiki_tree_context",
            "doc_id": "wiki-doc-1",
            "workspace": "workspace-1",
        }
    )


def _wiki_response_payload() -> dict:
    return {
        "ok": True,
        "doc_id": "wiki-doc-1",
        "source_name": "Opportunity PRD",
        "tree_type": "reasoning_action",
        "tree_json": {"id": "root", "kind": "root", "title": "Opportunity PRD", "children": []},
        "outline_md": "# Opportunity PRD",
        "dimension_bundle": {"markdown": "dimension markdown"},
        "raw_bundle": {"markdown": "raw markdown"},
        "version": 3,
    }


def _response(status_code: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "http://wiki.local/api/wiki/tree/context"),
    )


def test_fetch_wiki_tree_context_posts_expected_request_and_normalizes_response() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _response(200, _wiki_response_payload())

    service = PrdContextService(base_url="http://wiki.local/", timeout_seconds=7, http_post=fake_post)

    context = service.fetch_wiki_tree_context(_source())

    assert captured["url"] == "http://wiki.local/api/wiki/tree/context"
    assert captured["kwargs"]["headers"]["LIGHTRAG-WORKSPACE"] == "workspace-1"
    assert captured["kwargs"]["json"] == {
        "doc_id": "wiki-doc-1",
        "tree_type": "reasoning_action",
        "force_rebuild": False,
    }
    assert captured["kwargs"]["max_retries"] == 0
    assert isinstance(captured["kwargs"]["timeout"], httpx.Timeout)
    assert context.tree_json["kind"] == "root"
    assert context.dimension_markdown == "dimension markdown"


def test_fetch_wiki_tree_context_fails_when_tree_json_missing() -> None:
    def fake_post(_url: str, **_kwargs: Any) -> httpx.Response:
        payload = _wiki_response_payload()
        del payload["tree_json"]
        return _response(200, payload)

    service = PrdContextService(base_url="http://wiki.local", http_post=fake_post)

    with pytest.raises(PrdContextServiceError) as exc_info:
        service.fetch_wiki_tree_context(_source())

    assert exc_info.value.code == "wiki_context_invalid_response"
    assert "tree_json" in str(exc_info.value)


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_text"),
    [
        (500, "wiki_context_server_error", "HTTP 500"),
        (401, "wiki_context_forbidden", "denied access"),
        (403, "wiki_context_forbidden", "denied access"),
    ],
)
def test_fetch_wiki_tree_context_maps_http_errors(
    status_code: int,
    expected_code: str,
    expected_text: str,
) -> None:
    def fake_post(_url: str, **_kwargs: Any) -> httpx.Response:
        return _response(status_code, {"message": "Wiki failed"})

    service = PrdContextService(base_url="http://wiki.local", http_post=fake_post)

    with pytest.raises(PrdContextServiceError) as exc_info:
        service.fetch_wiki_tree_context(_source())

    assert exc_info.value.code == expected_code
    assert expected_text in str(exc_info.value)


def test_fetch_wiki_tree_context_maps_timeout() -> None:
    def fake_post(_url: str, **_kwargs: Any) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    service = PrdContextService(base_url="http://wiki.local", timeout_seconds=3, http_post=fake_post)

    with pytest.raises(PrdContextServiceError) as exc_info:
        service.fetch_wiki_tree_context(_source())

    assert exc_info.value.code == "wiki_context_timeout"
    assert "timed out after 3s" in str(exc_info.value)


def test_fetch_wiki_tree_context_large_response_returns_warning() -> None:
    def fake_post(_url: str, **_kwargs: Any) -> httpx.Response:
        payload = _wiki_response_payload()
        payload["raw_bundle"] = {"markdown": "raw" * 10_000}
        return _response(200, payload)

    service = PrdContextService(base_url="http://wiki.local", http_post=fake_post)

    context = service.fetch_wiki_tree_context(_source())

    assert context.raw_markdown_excerpt is not None
    assert context.raw_markdown_excerpt.endswith("...[truncated]")
    assert any("raw_bundle.markdown" in warning for warning in context.warnings)
