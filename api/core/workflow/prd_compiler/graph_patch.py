"""Typed graph patch support for natural-language workflow editing.

This module contains the side-effect-free part of the NL edit feature: patch
schemas, LLM patch planning, and in-memory patch application. Draft writes stay
in ``services.workflow_graph_edit_service`` so this module remains portable.
"""

from __future__ import annotations

import copy
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

import json_repair
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.workflow.prd_compiler.entities import PrdWorkflowDraftResponse, PrdWorkflowModelConfig
from fields.base import ResponseModel
from graphon.model_runtime.entities.message_entities import SystemPromptMessage, UserPromptMessage

_PROMPT_PATH = Path(__file__).parent / "prompts" / "graph_patch.md"
_JSON_RETRY_HINT = "Return only a valid JSON object matching the graph patch schema. No Markdown or prose."


class GraphPatchOperationType(StrEnum):
    ADD_NODE = "add_node"
    UPDATE_NODE = "update_node"
    REMOVE_NODE = "remove_node"
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"


class GraphPatchOperation(BaseModel):
    """One typed graph patch operation."""

    op: GraphPatchOperationType
    node_id: str | None = None
    edge_id: str | None = None
    node: dict[str, Any] | None = None
    edge: dict[str, Any] | None = None
    updates: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class WorkflowGraphPatch(BaseModel):
    """Patch envelope returned by the planner and echoed to the frontend."""

    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    operations: list[GraphPatchOperation] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WorkflowGraphEditPayload(BaseModel):
    """HTTP payload for previewing or applying a natural-language graph edit."""

    instruction: str = Field(min_length=1)
    selected_node_id: str | None = None
    scope: Literal["workflow", "selected_node"] = "workflow"
    dry_run: bool = True
    draft_hash: str | None = None
    model_config_data: PrdWorkflowModelConfig = Field(..., alias="model_config")
    patch: WorkflowGraphPatch | None = None

    model_config = ConfigDict(extra="forbid")


class WorkflowGraphEditResponse(ResponseModel):
    result: str
    draft_synced: bool
    workflow: PrdWorkflowDraftResponse
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    patch: WorkflowGraphPatch | None = None
    graph: dict[str, Any] | None = None
    graph_summary: dict[str, Any] | None = None


class WorkflowGraphPatchError(RuntimeError):
    """Raised when patch planning or application fails."""

    code: str

    def __init__(self, message: str, *, code: str = "workflow_graph_patch_error") -> None:
        super().__init__(message)
        self.code = code


class WorkflowGraphPatchPlanner:
    """Use an LLM to turn a natural-language instruction into typed patch JSON."""

    @classmethod
    def plan(
        cls,
        *,
        model_instance: Any,
        model_parameters: dict[str, Any],
        graph: dict[str, Any],
        instruction: str,
        selected_node_id: str | None,
        scope: str,
    ) -> WorkflowGraphPatch:
        payload = cls._invoke_and_parse_json(
            model_instance=model_instance,
            model_parameters=model_parameters,
            graph=graph,
            instruction=instruction,
            selected_node_id=selected_node_id,
            scope=scope,
        )
        try:
            return WorkflowGraphPatch.model_validate(payload)
        except ValidationError as exc:
            raise WorkflowGraphPatchError(
                f"LLM returned invalid graph patch fields: {exc.errors()}",
                code="workflow_graph_patch_invalid_shape",
            ) from exc

    @classmethod
    def _invoke_and_parse_json(
        cls,
        *,
        model_instance: Any,
        model_parameters: dict[str, Any],
        graph: dict[str, Any],
        instruction: str,
        selected_node_id: str | None,
        scope: str,
    ) -> dict[str, Any]:
        messages = cls._messages(
            graph=graph,
            instruction=instruction,
            selected_node_id=selected_node_id,
            scope=scope,
        )
        last_error = ""
        for attempt in range(2):
            attempt_messages = messages if attempt == 0 else [*messages, UserPromptMessage(content=_JSON_RETRY_HINT)]
            response = model_instance.invoke_llm(
                prompt_messages=attempt_messages,
                model_parameters=model_parameters,
                stream=False,
            )
            text = response.message.get_text_content() or ""
            try:
                parsed = json_repair.loads(text)
            except Exception as exc:
                last_error = str(exc)
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = f"LLM returned {type(parsed).__name__}, expected JSON object."

        raise WorkflowGraphPatchError(
            f"LLM returned non-JSON graph patch: {last_error or 'JSON parse failed'}",
            code="workflow_graph_patch_invalid_json",
        )

    @classmethod
    def _messages(
        cls,
        *,
        graph: dict[str, Any],
        instruction: str,
        selected_node_id: str | None,
        scope: str,
    ) -> list[Any]:
        user_payload = {
            "instruction": instruction,
            "selected_node_id": selected_node_id,
            "scope": scope,
            "graph": _sanitize_graph_for_planner(graph),
        }
        return [
            SystemPromptMessage(content=_PROMPT_PATH.read_text(encoding="utf-8")),
            UserPromptMessage(
                content=(
                    "Create a typed patch for this Dify workflow graph:\n"
                    f"{json.dumps(user_payload, ensure_ascii=False, separators=(',', ':'))}"
                )
            ),
        ]


def apply_graph_patch(graph: dict[str, Any], patch: WorkflowGraphPatch) -> dict[str, Any]:
    """Apply a typed graph patch to a graph copy and return the preview graph."""
    preview_graph = copy.deepcopy(graph)
    nodes = _nodes(preview_graph)
    edges = _edges(preview_graph)

    for operation in patch.operations:
        match operation.op:
            case GraphPatchOperationType.ADD_NODE:
                _apply_add_node(nodes=nodes, operation=operation)
            case GraphPatchOperationType.UPDATE_NODE:
                _apply_update_node(nodes=nodes, operation=operation)
            case GraphPatchOperationType.REMOVE_NODE:
                _apply_remove_node(nodes=nodes, edges=edges, operation=operation)
            case GraphPatchOperationType.ADD_EDGE:
                _apply_add_edge(edges=edges, operation=operation)
            case GraphPatchOperationType.REMOVE_EDGE:
                _apply_remove_edge(edges=edges, operation=operation)

    return preview_graph


def _sanitize_graph_for_planner(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": str(node.get("id") or ""),
                "type": str(_node_data(node).get("type") or ""),
                "title": str(_node_data(node).get("title") or ""),
                "desc": str(_node_data(node).get("desc") or ""),
            }
            for node in _nodes(graph)
        ],
        "edges": [
            {
                "id": str(edge.get("id") or ""),
                "source": str(edge.get("source") or ""),
                "target": str(edge.get("target") or ""),
                "sourceHandle": str(edge.get("sourceHandle") or ""),
            }
            for edge in _edges(graph)
        ],
    }


def _apply_add_node(*, nodes: list[dict[str, Any]], operation: GraphPatchOperation) -> None:
    if not isinstance(operation.node, dict):
        raise WorkflowGraphPatchError("add_node requires node.", code="graph_patch_missing_node")
    node_id = str(operation.node.get("id") or "")
    if not node_id:
        raise WorkflowGraphPatchError("add_node requires node.id.", code="graph_patch_missing_node_id")
    if _find_by_id(nodes, node_id):
        raise WorkflowGraphPatchError(f"Node '{node_id}' already exists.", code="graph_patch_duplicate_node")
    nodes.append(copy.deepcopy(operation.node))


def _apply_update_node(*, nodes: list[dict[str, Any]], operation: GraphPatchOperation) -> None:
    if not operation.node_id:
        raise WorkflowGraphPatchError("update_node requires node_id.", code="graph_patch_missing_node_id")
    if not isinstance(operation.updates, dict):
        raise WorkflowGraphPatchError("update_node requires updates.", code="graph_patch_missing_updates")
    if "id" in operation.updates:
        raise WorkflowGraphPatchError("update_node cannot change node id.", code="graph_patch_immutable_node_id")
    node = _find_by_id(nodes, operation.node_id)
    if node is None:
        raise WorkflowGraphPatchError(f"Node '{operation.node_id}' not found.", code="graph_patch_node_not_found")
    _deep_merge(node, operation.updates)


def _apply_remove_node(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operation: GraphPatchOperation,
) -> None:
    if not operation.node_id:
        raise WorkflowGraphPatchError("remove_node requires node_id.", code="graph_patch_missing_node_id")
    node = _find_by_id(nodes, operation.node_id)
    if node is None:
        raise WorkflowGraphPatchError(f"Node '{operation.node_id}' not found.", code="graph_patch_node_not_found")
    nodes[:] = [candidate for candidate in nodes if str(candidate.get("id") or "") != operation.node_id]
    edges[:] = [
        edge
        for edge in edges
        if str(edge.get("source") or "") != operation.node_id and str(edge.get("target") or "") != operation.node_id
    ]


def _apply_add_edge(*, edges: list[dict[str, Any]], operation: GraphPatchOperation) -> None:
    if not isinstance(operation.edge, dict):
        raise WorkflowGraphPatchError("add_edge requires edge.", code="graph_patch_missing_edge")
    edge_id = str(operation.edge.get("id") or "")
    if not edge_id:
        raise WorkflowGraphPatchError("add_edge requires edge.id.", code="graph_patch_missing_edge_id")
    if _find_by_id(edges, edge_id):
        raise WorkflowGraphPatchError(f"Edge '{edge_id}' already exists.", code="graph_patch_duplicate_edge")
    edges.append(copy.deepcopy(operation.edge))


def _apply_remove_edge(*, edges: list[dict[str, Any]], operation: GraphPatchOperation) -> None:
    if operation.edge_id:
        edges[:] = [edge for edge in edges if str(edge.get("id") or "") != operation.edge_id]
        return
    if not isinstance(operation.edge, dict):
        raise WorkflowGraphPatchError("remove_edge requires edge_id or edge.", code="graph_patch_missing_edge")
    source = str(operation.edge.get("source") or "")
    target = str(operation.edge.get("target") or "")
    edges[:] = [
        edge
        for edge in edges
        if str(edge.get("source") or "") != source or str(edge.get("target") or "") != target
    ]


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise WorkflowGraphPatchError("graph.nodes must be a list.", code="graph_patch_invalid_graph")
    if not all(isinstance(node, dict) for node in nodes):
        raise WorkflowGraphPatchError("graph.nodes must contain objects.", code="graph_patch_invalid_graph")
    return cast(list[dict[str, Any]], nodes)


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    edges = graph.get("edges")
    if not isinstance(edges, list):
        raise WorkflowGraphPatchError("graph.edges must be a list.", code="graph_patch_invalid_graph")
    if not all(isinstance(edge, dict) for edge in edges):
        raise WorkflowGraphPatchError("graph.edges must contain objects.", code="graph_patch_invalid_graph")
    return cast(list[dict[str, Any]], edges)


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("id") or "") == item_id), None)


def _deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
