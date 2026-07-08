from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.workflow.prd_compiler.entities import PrdWorkflowGeneratePayload


def _payload() -> dict:
    return {
        "app_id": "app-1",
        "source": {
            "type": "wiki_tree_context",
            "doc_id": "wiki-doc-1",
            "workspace": "workspace-1",
        },
        "model_config": {
            "provider": "langgenius/tongyi/tongyi",
            "name": "qwen-plus",
            "mode": "chat",
            "completion_params": {},
        },
    }


def test_prd_workflow_generate_payload_defaults_wiki_source() -> None:
    payload = PrdWorkflowGeneratePayload.model_validate(_payload())

    assert payload.source.tree_type == "reasoning_action"
    assert payload.source.force_rebuild is False
    assert payload.sync_to_draft is True
    assert payload.overwrite_policy == "require_confirmation"
    assert payload.draft_hash is None


def test_prd_workflow_generate_payload_requires_doc_id() -> None:
    raw = _payload()
    del raw["source"]["doc_id"]

    with pytest.raises(ValidationError) as exc_info:
        PrdWorkflowGeneratePayload.model_validate(raw)

    assert exc_info.value.errors()[0]["loc"] == ("source", "doc_id")


def test_prd_workflow_generate_payload_forbids_extra_fields() -> None:
    raw = _payload()
    raw["unexpected"] = True

    with pytest.raises(ValidationError):
        PrdWorkflowGeneratePayload.model_validate(raw)


def test_prd_workflow_generate_payload_forbids_extra_source_fields() -> None:
    raw = _payload()
    raw["source"]["unexpected"] = True

    with pytest.raises(ValidationError):
        PrdWorkflowGeneratePayload.model_validate(raw)


def test_prd_workflow_generate_payload_forbids_extra_model_config_fields() -> None:
    raw = _payload()
    raw["model_config"]["unexpected"] = True

    with pytest.raises(ValidationError):
        PrdWorkflowGeneratePayload.model_validate(raw)


def test_prd_workflow_generate_payload_requires_public_model_config_alias() -> None:
    raw = _payload()
    raw["model_config_data"] = raw.pop("model_config")

    with pytest.raises(ValidationError):
        PrdWorkflowGeneratePayload.model_validate(raw)
