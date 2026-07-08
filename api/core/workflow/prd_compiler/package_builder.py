"""Build the strict custom package artifact from a published Dify workflow.

The package format is a business artifact, not a Dify DSL export. This module
therefore accepts only plain metadata plus Dify graph JSON and emits a ZIP with
the user-approved top-level layout. It deliberately does not persist anything,
does not include graph/IR/validation/source metadata, and avoids copying full
Dify prompts into generated skill instructions.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

import yaml

ALLOWED_TOP_LEVEL_ENTRIES = frozenset({"package.yaml", "workflow.yaml", "skills", "schemas", "data"})
FORBIDDEN_PACKAGE_MARKERS = (
    "workflow.dsl.yaml",
    "graph.json",
    "manifest.lock",
    "compile/",
    "dify/",
    "prompt_template",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
)


class PackagePhase(TypedDict):
    id: str
    title: str
    skill: str
    goal: str
    context: NotRequired[dict[str, list[str]]]
    confirmation: NotRequired[str]


class PackageBuildError(ValueError):
    """Raised when a workflow cannot be exported as the strict package format."""


@dataclass(frozen=True)
class WorkflowPackageArtifact:
    """In-memory downloadable package created within one request lifecycle."""

    package_id: str
    version: str
    filename: str
    payload: bytes


def build_workflow_package_zip(
    *,
    package_id: str,
    version: str,
    title: str,
    scenario: str,
    graph: dict[str, Any],
) -> WorkflowPackageArtifact:
    """Build a ZIP artifact with the strict package top-level structure."""
    normalized_package_id = _slugify(package_id or title or "workflow-package")
    normalized_version = _safe_version(version)
    phases, skill_files, schema_files = _build_package_parts(graph=graph)
    if not phases:
        raise PackageBuildError("Published workflow has no exportable package phases.")

    package_yaml = {
        "id": normalized_package_id,
        "version": normalized_version,
        "title": title or normalized_package_id,
        "scenario": scenario or "",
        "entry_workflow": "workflow.yaml",
    }
    workflow_yaml = {
        "id": normalized_package_id,
        "entry_phase": phases[0]["id"],
        "phases": phases,
    }

    payload = _write_package_zip(
        package_yaml=package_yaml,
        workflow_yaml=workflow_yaml,
        skill_files=skill_files,
        schema_files=schema_files,
    )
    _assert_package_is_safe(payload)
    return WorkflowPackageArtifact(
        package_id=normalized_package_id,
        version=normalized_version,
        filename=f"{normalized_package_id}-{normalized_version}.zip",
        payload=payload,
    )


def _build_package_parts(
    *,
    graph: dict[str, Any],
) -> tuple[list[PackagePhase], dict[str, str], dict[str, str]]:
    nodes = _graph_nodes(graph)
    exportable_nodes = [node for node in nodes if _is_exportable_phase_node(node)]
    node_id_to_phase_id = {str(node.get("id")): _slugify(str(node.get("id") or "phase")) for node in exportable_nodes}
    node_id_to_skill_id = _build_skill_ids(exportable_nodes)
    upstream_phase_ids = _build_upstream_phase_ids(graph=graph, node_id_to_phase_id=node_id_to_phase_id)

    phases: list[PackagePhase] = []
    skill_files: dict[str, str] = {}
    schema_files: dict[str, str] = {}
    for node in exportable_nodes:
        node_id = str(node.get("id") or "")
        phase_id = node_id_to_phase_id[node_id]
        skill_id = node_id_to_skill_id[node_id]
        data = _node_data(node)
        title = str(data.get("title") or phase_id)
        goal = _node_goal(data)
        schema_path = f"schemas/{phase_id}.schema.json"
        phase: PackagePhase = {
            "id": phase_id,
            "title": title,
            "skill": skill_id,
            "goal": goal,
        }
        upstream = upstream_phase_ids.get(node_id, [])
        if upstream:
            phase["context"] = {"load_phase_outputs": upstream}
        confirmation = _node_confirmation(data)
        if confirmation:
            phase["confirmation"] = confirmation
        phases.append(phase)
        skill_files[f"skills/{skill_id}/skill.md"] = _render_skill_md(
            skill_id=skill_id,
            title=title,
            goal=goal,
            model_name=_node_model_name(data),
            schema_path=schema_path,
            phase_id=phase_id,
            upstream_phase_ids=upstream,
        )
        schema_files[schema_path] = json.dumps(_schema_for_node(node), ensure_ascii=False, indent=2)

    return phases, skill_files, schema_files


def _graph_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise PackageBuildError("Published workflow graph must contain nodes.")
    return [node for node in nodes if isinstance(node, dict)]


def _build_skill_ids(nodes: list[dict[str, Any]]) -> dict[str, str]:
    counts: dict[str, int] = {}
    skill_ids: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        data = _node_data(node)
        base = _slugify(str(data.get("title") or node_id or "skill"))
        index = counts.get(base, 0) + 1
        counts[base] = index
        skill_ids[node_id] = base if index == 1 else f"{base}-{index}"
    return skill_ids


def _build_upstream_phase_ids(
    *,
    graph: dict[str, Any],
    node_id_to_phase_id: dict[str, str],
) -> dict[str, list[str]]:
    upstream: dict[str, list[str]] = {}
    edges = graph.get("edges")
    if not isinstance(edges, list):
        return upstream

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        source_phase_id = node_id_to_phase_id.get(source)
        target_phase_id = node_id_to_phase_id.get(target)
        if not source_phase_id or not target_phase_id:
            continue
        upstream.setdefault(target, [])
        if source_phase_id not in upstream[target]:
            upstream[target].append(source_phase_id)
    return upstream


def _render_skill_md(
    *,
    skill_id: str,
    title: str,
    goal: str,
    model_name: str,
    schema_path: str,
    phase_id: str,
    upstream_phase_ids: list[str],
) -> str:
    context_policy: dict[str, Any] = {"own_phase": phase_id}
    if upstream_phase_ids:
        context_policy["load_phase_outputs"] = upstream_phase_ids

    front_matter = {
        "name": skill_id,
        "description": goal or title,
        "model": model_name,
        "tools": [],
        "output_schema": schema_path,
        "context_policy": context_policy,
    }
    body = (
        f"# {title} 指令\n\n"
        "## 目标\n"
        f"{goal or title}\n\n"
        "## 执行要求\n"
        "- 根据当前 phase 的输入和上游 phase 产物完成任务。\n"
        "- 输出必须结构化、可复盘，并符合声明的 output_schema。\n"
        "- 不要生成、暴露或猜测任何真实密钥、凭证、API Key。\n"
    )
    return f"---\n{_dump_yaml(front_matter)}---\n\n{body}"


def _schema_for_node(node: dict[str, Any]) -> dict[str, Any]:
    data = _node_data(node)
    node_type = _node_type(node)
    if node_type == "code":
        outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
        properties = {
            str(name): {"type": _json_schema_type(str(config.get("type") or "string"))}
            for name, config in outputs.items()
            if isinstance(config, dict)
        }
        if properties:
            return {
                "type": "object",
                "required": sorted(properties),
                "properties": properties,
            }

    if node_type == "end":
        outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
        properties = {
            str(output.get("variable") or "result"): {"type": "string"}
            for output in outputs
            if isinstance(output, dict)
        }
        if properties:
            return {
                "type": "object",
                "required": sorted(properties),
                "properties": properties,
            }

    if node_type == "if-else":
        return {
            "type": "object",
            "required": ["selected_case_id"],
            "properties": {
                "selected_case_id": {"type": "string"},
                "reason": {"type": "string"},
            },
        }

    if node_type == "knowledge-retrieval":
        return {
            "type": "object",
            "required": ["result"],
            "properties": {
                "result": {"type": "array", "items": {"type": "object"}},
            },
        }

    if node_type == "http-request":
        return {
            "type": "object",
            "required": ["body", "status_code"],
            "properties": {
                "body": {"type": "string"},
                "status_code": {"type": "number"},
                "headers": {"type": "object"},
                "files": {"type": "array", "items": {"type": "object"}},
            },
        }

    if node_type == "tool":
        return {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "files": {"type": "array", "items": {"type": "object"}},
                "json": {"type": "array", "items": {"type": "object"}},
            },
        }

    if node_type == "human-input":
        form_inputs = data.get("inputs") if isinstance(data.get("inputs"), list) else []
        form_properties = {
            str(form_input.get("output_variable_name")): {"type": "string"}
            for form_input in form_inputs
            if isinstance(form_input, dict) and form_input.get("output_variable_name")
        }
        properties = {
            "__action_id": {"type": "string"},
            "__action_value": {"type": "string"},
            "__rendered_content": {"type": "string"},
            **form_properties,
        }
        return {
            "type": "object",
            "required": sorted(properties),
            "properties": properties,
        }

    return {
        "type": "object",
        "required": ["result"],
        "properties": {
            "result": {"type": "string"},
        },
    }


def _write_package_zip(
    *,
    package_yaml: dict[str, Any],
    workflow_yaml: dict[str, Any],
    skill_files: dict[str, str],
    schema_files: dict[str, str],
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("skills/", "")
        archive.writestr("schemas/", "")
        archive.writestr("data/", "")
        archive.writestr("package.yaml", _dump_yaml(package_yaml))
        archive.writestr("workflow.yaml", _dump_yaml(workflow_yaml))
        for path, content in sorted(skill_files.items()):
            archive.writestr(path, content)
        for path, content in sorted(schema_files.items()):
            archive.writestr(path, content)
    return buffer.getvalue()


def _assert_package_is_safe(payload: bytes) -> None:
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        top_level_entries = {name.rstrip("/").split("/", 1)[0] for name in names}
        if top_level_entries != ALLOWED_TOP_LEVEL_ENTRIES:
            raise PackageBuildError("Package top-level structure does not match the strict format.")
        for name in names:
            if _is_forbidden_package_path(name):
                raise PackageBuildError(f"Package contains forbidden artifact path: {name}")
            if not name.endswith("/"):
                texts.append(archive.read(name).decode("utf-8", errors="ignore"))

    text = "\n".join(texts)
    for marker in FORBIDDEN_PACKAGE_MARKERS:
        if marker in text:
            raise PackageBuildError(f"Package contains forbidden compiler artifact marker: {marker}")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise PackageBuildError("Package contains content that looks like a secret.")


def _is_forbidden_package_path(name: str) -> bool:
    normalized = name.strip("/")
    if normalized in {"README.md", "manifest.lock", "workflow.dsl.yaml", "graph.json"}:
        return True
    return normalized.startswith(("dify/", "compile/"))


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _node_type(node: dict[str, Any]) -> str:
    return str(_node_data(node).get("type") or "")


def _is_exportable_phase_node(node: dict[str, Any]) -> bool:
    return _node_type(node) not in {"start", "trigger-webhook", "trigger-schedule", "trigger-plugin"}


def _node_goal(data: dict[str, Any]) -> str:
    desc = data.get("desc")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    title = data.get("title")
    return str(title or "").strip()


def _node_model_name(data: dict[str, Any]) -> str:
    model = data.get("model")
    if not isinstance(model, dict):
        return "workflow-control"
    return str(model.get("name") or "workflow-control")


def _node_confirmation(data: dict[str, Any]) -> str | None:
    confirmation = data.get("confirmation")
    if isinstance(confirmation, str) and confirmation.strip():
        return confirmation.strip()
    return None


def _safe_version(version: str) -> str:
    normalized = version.strip()
    return normalized or "0.1.0"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-_")
    return slug or "item"


def _json_schema_type(value: str) -> str:
    match value:
        case "number" | "integer":
            return "number"
        case "boolean" | "bool":
            return "boolean"
        case "array" | "array[string]" | "array[number]" | "array[object]":
            return "array"
        case "object":
            return "object"
        case _:
            return "string"


def _dump_yaml(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
