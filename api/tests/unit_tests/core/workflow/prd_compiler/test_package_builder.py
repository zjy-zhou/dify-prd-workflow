from __future__ import annotations

import io
import json
import zipfile

import pytest
import yaml

from core.workflow.prd_compiler.package_builder import PackageBuildError, build_workflow_package_zip


def _graph() -> dict:
    return {
        "nodes": [
            {
                "id": "start",
                "data": {
                    "type": "start",
                    "title": "Start",
                    "variables": [{"variable": "prd_context", "type": "paragraph"}],
                },
            },
            {
                "id": "analyze-prd",
                "data": {
                    "type": "llm",
                    "title": "Analyze PRD",
                    "desc": "Analyze the structured PRD and produce an implementation plan.",
                    "model": {"name": "qwen-plus"},
                    "prompt_template": [{"role": "user", "text": "Do not export this prompt."}],
                },
            },
            {
                "id": "final-answer",
                "data": {
                    "type": "end",
                    "title": "Final Answer",
                    "desc": "Return the final package-ready plan.",
                    "outputs": [{"variable": "answer", "value_selector": ["analyze-prd", "text"]}],
                },
            },
        ],
        "edges": [
            {"source": "start", "target": "analyze-prd"},
            {"source": "analyze-prd", "target": "final-answer"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _expanded_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "webhook",
                "data": {
                    "type": "trigger-webhook",
                    "title": "Webhook",
                    "webhook_url": "https://example.com/webhook/run",
                    "variables": [{"variable": "query", "value_type": "string"}],
                },
            },
            {
                "id": "call-api",
                "data": {
                    "type": "http-request",
                    "title": "Call API",
                    "desc": "Call approved internal API.",
                    "url": "https://example.com/internal/search",
                    "method": "post",
                },
            },
            {
                "id": "transform",
                "data": {
                    "type": "code",
                    "title": "Transform",
                    "desc": "Normalize API response.",
                    "code": "def main(body: str) -> dict:\n    return {\"summary\": body}",
                    "outputs": {"summary": {"type": "string", "children": None}},
                },
            },
            {
                "id": "review",
                "data": {
                    "type": "human-input",
                    "title": "Review",
                    "desc": "Human review.",
                    "form_content": "Review the generated summary.",
                    "inputs": [{"type": "paragraph", "output_variable_name": "approval"}],
                    "user_actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
                },
            },
        ],
        "edges": [
            {"source": "webhook", "target": "call-api"},
            {"source": "call-api", "target": "transform"},
            {"source": "transform", "target": "review"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _zip_files(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def test_build_workflow_package_zip_uses_strict_top_level_layout() -> None:
    artifact = build_workflow_package_zip(
        package_id="PRD Opportunity Workflow",
        version="2026.07.08",
        title="PRD Opportunity Workflow",
        scenario="Compile a PRD into a workflow package.",
        graph=_graph(),
    )

    with zipfile.ZipFile(io.BytesIO(artifact.payload)) as archive:
        names = archive.namelist()

    assert artifact.filename == "prd-opportunity-workflow-2026.07.08.zip"
    assert {name.rstrip("/").split("/", 1)[0] for name in names} == {
        "package.yaml",
        "workflow.yaml",
        "skills",
        "schemas",
        "data",
    }
    assert "package.yaml" in names
    assert "workflow.yaml" in names
    assert "skills/analyze-prd/skill.md" in names
    assert "schemas/analyze-prd.schema.json" in names
    assert "data/" in names


def test_build_workflow_package_zip_outputs_parseable_package_files() -> None:
    artifact = build_workflow_package_zip(
        package_id="prd-package",
        version="0.1.0",
        title="PRD Package",
        scenario="Compile a PRD.",
        graph=_graph(),
    )
    files = _zip_files(artifact.payload)

    package_yaml = yaml.safe_load(files["package.yaml"].decode())
    workflow_yaml = yaml.safe_load(files["workflow.yaml"].decode())
    skill_md = files["skills/analyze-prd/skill.md"].decode()
    schema = json.loads(files["schemas/final-answer.schema.json"].decode())

    assert package_yaml["entry_workflow"] == "workflow.yaml"
    assert workflow_yaml["entry_phase"] == "analyze-prd"
    assert workflow_yaml["phases"][1]["context"] == {"load_phase_outputs": ["analyze-prd"]}
    assert "output_schema: schemas/analyze-prd.schema.json" in skill_md
    assert schema["required"] == ["answer"]


def test_build_workflow_package_zip_does_not_export_graph_or_dify_prompt() -> None:
    artifact = build_workflow_package_zip(
        package_id="prd-package",
        version="0.1.0",
        title="PRD Package",
        scenario="Compile a PRD.",
        graph=_graph(),
    )
    files = _zip_files(artifact.payload)
    combined_text = "\n".join(content.decode() for content in files.values())

    assert "prompt_template" not in combined_text
    assert "Do not export this prompt" not in combined_text
    assert "graph.json" not in files
    assert "workflow.dsl.yaml" not in files


def test_build_workflow_package_zip_rejects_secret_like_content() -> None:
    graph = _graph()
    graph["nodes"][1]["data"]["desc"] = "Use api_key = sk-abcdefghijklmnopqrstuvwxyz"

    with pytest.raises(PackageBuildError):
        build_workflow_package_zip(
            package_id="prd-package",
            version="0.1.0",
            title="PRD Package",
            scenario="Compile a PRD.",
            graph=graph,
        )


def test_build_workflow_package_zip_exports_second_stage_node_schemas_and_excludes_triggers() -> None:
    artifact = build_workflow_package_zip(
        package_id="expanded-package",
        version="0.2.0",
        title="Expanded Package",
        scenario="Export second-stage nodes.",
        graph=_expanded_graph(),
    )
    files = _zip_files(artifact.payload)

    workflow_yaml = yaml.safe_load(files["workflow.yaml"].decode())
    phase_ids = [phase["id"] for phase in workflow_yaml["phases"]]
    http_schema = json.loads(files["schemas/call-api.schema.json"].decode())
    code_schema = json.loads(files["schemas/transform.schema.json"].decode())
    human_schema = json.loads(files["schemas/review.schema.json"].decode())

    assert "webhook" not in phase_ids
    assert {"call-api", "transform", "review"} <= set(phase_ids)
    assert http_schema["required"] == ["body", "status_code"]
    assert code_schema["required"] == ["summary"]
    assert "__action_id" in human_schema["properties"]
    assert "approval" in human_schema["properties"]
