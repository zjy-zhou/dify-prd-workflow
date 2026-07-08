"""Normalized Wiki Tree Context input for the PRD workflow compiler.

The Wiki API can return very large recursive trees plus full raw Markdown. This
module converts that response into the smaller compiler input used by later LLM
planning stages. It keeps action-oriented tree nodes first and never exposes the
full raw PRD by default.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PRIORITY_TREE_NODE_KINDS = frozenset({"action", "condition", "outcome", "rule"})
STRUCTURAL_TREE_NODE_KINDS = frozenset({"root", "section"})

MAX_TREE_JSON_CHARS = 120_000
MAX_OUTLINE_MARKDOWN_CHARS = 40_000
MAX_DIMENSION_MARKDOWN_CHARS = 40_000
MAX_RAW_MARKDOWN_EXCERPT_CHARS = 8_000
PRIORITY_TEXT_CHARS = 4_000
STRUCTURAL_TEXT_CHARS = 1_000

_STRUCTURAL_FIELDS = ("id", "kind", "title", "summary", "schema_field", "schema_section", "render")
_PRIORITY_FIELDS = (*_STRUCTURAL_FIELDS, "content")
_ROOT_EXTRA_FIELDS = ("schema_id", "tree_type")


class WikiContextNormalizationError(ValueError):
    """Raised when the Wiki API response cannot become compiler input."""


class PrdWikiContext(BaseModel):
    """PRD compiler input resolved from the Wiki Tree Context API.

    ``tree_json`` may be pruned from the original API response when it is too
    large. ``raw_markdown_excerpt`` is intentionally an excerpt; downstream LLM
    prompts should rely on the structured tree and only use raw snippets as
    supporting evidence.
    """

    doc_id: str
    workspace: str
    source_name: str = ""
    version: int | None = None
    tree_type: str
    tree_json: dict[str, Any]
    outline_md: str = ""
    dimension_markdown: str = ""
    raw_markdown_excerpt: str | None = None
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def normalize_wiki_tree_context_response(
    payload: Mapping[str, Any],
    *,
    doc_id: str,
    workspace: str,
    tree_type: str,
    max_tree_json_chars: int = MAX_TREE_JSON_CHARS,
    max_outline_markdown_chars: int = MAX_OUTLINE_MARKDOWN_CHARS,
    max_dimension_markdown_chars: int = MAX_DIMENSION_MARKDOWN_CHARS,
    max_raw_markdown_excerpt_chars: int = MAX_RAW_MARKDOWN_EXCERPT_CHARS,
) -> PrdWikiContext:
    """Validate and compact a Wiki Tree Context API response.

    Args:
        payload: Decoded JSON response from ``POST /api/wiki/tree/context``.
        doc_id: Requested Wiki document id, used as a fallback when the API
            omits ``doc_id``.
        workspace: Requested LIGHTRAG workspace id.
        tree_type: Requested tree type, used as a fallback when the API omits
            ``tree_type``.
        max_tree_json_chars: Character budget for serialized tree JSON before
            priority pruning is applied.
        max_outline_markdown_chars: Character budget for ``outline_md``.
        max_dimension_markdown_chars: Character budget for dimension markdown.
        max_raw_markdown_excerpt_chars: Character budget for raw markdown
            snippets. The full raw Markdown is not included by default.

    Raises:
        WikiContextNormalizationError: If required structured fields are absent
            or malformed.
    """
    tree_json_raw = payload.get("tree_json")
    if not isinstance(tree_json_raw, Mapping):
        raise WikiContextNormalizationError("Wiki Tree Context API response is missing object field 'tree_json'.")

    warnings: list[str] = []
    tree_json = copy.deepcopy(dict(tree_json_raw))
    if _json_size(tree_json) > max_tree_json_chars:
        tree_json = _prioritize_tree_json(tree_json)
        warnings.append(
            "tree_json exceeded compiler input budget; kept action, condition, outcome, and rule nodes first."
        )

    outline_md, outline_truncated = _truncate_markdown(
        _string_or_empty(payload.get("outline_md")),
        max_outline_markdown_chars,
    )
    if outline_truncated:
        warnings.append("outline_md was truncated for compiler input.")

    dimension_markdown, dimension_truncated = _truncate_markdown(
        _bundle_markdown(payload.get("dimension_bundle")),
        max_dimension_markdown_chars,
    )
    if dimension_truncated:
        warnings.append("dimension_bundle.markdown was truncated for compiler input.")

    raw_markdown_excerpt, raw_truncated = _truncate_markdown(
        _bundle_markdown(payload.get("raw_bundle")),
        max_raw_markdown_excerpt_chars,
    )
    if raw_truncated:
        warnings.append("raw_bundle.markdown was excerpted; full raw PRD content was not included.")

    return PrdWikiContext(
        doc_id=_string_or_empty(payload.get("doc_id")) or doc_id,
        workspace=workspace,
        source_name=_string_or_empty(payload.get("source_name")),
        version=_optional_int(payload.get("version")),
        tree_type=_string_or_empty(payload.get("tree_type")) or tree_type,
        tree_json=tree_json,
        outline_md=outline_md,
        dimension_markdown=dimension_markdown,
        raw_markdown_excerpt=raw_markdown_excerpt or None,
        warnings=warnings,
    )


def _prioritize_tree_json(tree_json: dict[str, Any]) -> dict[str, Any]:
    pruned = _prioritize_tree_node(tree_json)
    return pruned if pruned is not None else {}


def _prioritize_tree_node(node: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = _string_or_empty(node.get("kind"))
    children = [_prioritize_tree_node(child) for child in _node_children(node)]
    kept_children = [child for child in children if child is not None]

    should_keep_node = kind in PRIORITY_TREE_NODE_KINDS or kind in STRUCTURAL_TREE_NODE_KINDS or bool(kept_children)
    if not should_keep_node:
        return None

    fields = _PRIORITY_FIELDS if kind in PRIORITY_TREE_NODE_KINDS else _STRUCTURAL_FIELDS
    result: dict[str, Any] = {}
    for field_name in fields:
        if field_name not in node:
            continue
        result[field_name] = _normalize_node_value(
            node[field_name],
            text_limit=PRIORITY_TEXT_CHARS if kind in PRIORITY_TREE_NODE_KINDS else STRUCTURAL_TEXT_CHARS,
        )

    for field_name in _ROOT_EXTRA_FIELDS:
        if field_name in node:
            result[field_name] = _normalize_node_value(node[field_name], text_limit=STRUCTURAL_TEXT_CHARS)

    if kept_children or "children" in node:
        result["children"] = kept_children

    return result


def _node_children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, Mapping)]


def _normalize_node_value(value: Any, *, text_limit: int) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, text_limit)
    return value


def _bundle_markdown(bundle: Any) -> str:
    if not isinstance(bundle, Mapping):
        return ""
    return _string_or_empty(bundle.get("markdown"))


def _truncate_markdown(value: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or not value:
        return "", bool(value)
    truncated = _truncate_text(value, max_chars)
    return truncated, truncated != value


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}\n...[truncated]"


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _string_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
