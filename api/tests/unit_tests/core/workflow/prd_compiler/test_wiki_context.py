from __future__ import annotations

import pytest

from core.workflow.prd_compiler.wiki_context import (
    WikiContextNormalizationError,
    normalize_wiki_tree_context_response,
)


def _wiki_payload() -> dict:
    return {
        "ok": True,
        "doc_id": "wiki-doc-1",
        "source_name": "Opportunity PRD",
        "tree_type": "reasoning_action",
        "tree_json": {
            "id": "root",
            "kind": "root",
            "title": "Opportunity PRD",
            "children": [
                {
                    "id": "action-1",
                    "kind": "action",
                    "title": "Find opportunity",
                    "content": "Analyze user and market signals.",
                    "children": [],
                }
            ],
        },
        "outline_md": "# Opportunity PRD",
        "dimension_bundle": {"markdown": "| dimension | value |"},
        "raw_bundle": {"markdown": "Full raw markdown"},
        "version": 3,
    }


def test_normalize_wiki_tree_context_response_reads_contract_fields() -> None:
    context = normalize_wiki_tree_context_response(
        _wiki_payload(),
        doc_id="wiki-doc-1",
        workspace="workspace-1",
        tree_type="reasoning_action",
    )

    assert context.doc_id == "wiki-doc-1"
    assert context.workspace == "workspace-1"
    assert context.source_name == "Opportunity PRD"
    assert context.version == 3
    assert context.tree_type == "reasoning_action"
    assert context.tree_json["children"][0]["kind"] == "action"
    assert context.outline_md == "# Opportunity PRD"
    assert context.dimension_markdown == "| dimension | value |"
    assert context.raw_markdown_excerpt == "Full raw markdown"
    assert context.warnings == []


def test_normalize_wiki_tree_context_response_requires_tree_json() -> None:
    payload = _wiki_payload()
    del payload["tree_json"]

    with pytest.raises(WikiContextNormalizationError, match="tree_json"):
        normalize_wiki_tree_context_response(
            payload,
            doc_id="wiki-doc-1",
            workspace="workspace-1",
            tree_type="reasoning_action",
        )


def test_normalize_wiki_tree_context_response_warns_and_prioritizes_large_tree() -> None:
    payload = _wiki_payload()
    payload["tree_json"]["children"] = [
        {
            "id": "note-1",
            "kind": "note",
            "title": "Verbose note",
            "content": "noise" * 200,
            "children": [],
        },
        {
            "id": "rule-1",
            "kind": "rule",
            "title": "Required rule",
            "content": "keep this rule" * 50,
            "children": [],
        },
    ]
    payload["raw_bundle"] = {"markdown": "raw" * 100}

    context = normalize_wiki_tree_context_response(
        payload,
        doc_id="wiki-doc-1",
        workspace="workspace-1",
        tree_type="reasoning_action",
        max_tree_json_chars=300,
        max_raw_markdown_excerpt_chars=20,
    )

    children = context.tree_json["children"]
    assert [child["kind"] for child in children] == ["rule"]
    assert children[0]["content"].startswith("keep this rule")
    assert context.raw_markdown_excerpt.endswith("...[truncated]")
    assert any("tree_json" in warning for warning in context.warnings)
    assert any("raw_bundle.markdown" in warning for warning in context.warnings)
