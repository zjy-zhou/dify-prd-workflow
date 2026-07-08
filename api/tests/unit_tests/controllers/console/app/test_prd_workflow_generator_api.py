from __future__ import annotations

from inspect import unwrap
from types import SimpleNamespace

import pytest
from flask import Flask
from pydantic import ValidationError

from controllers.console.app import prd_workflow_generator as module
from controllers.console.app.error import UnsupportedPrdWorkflowSourceError
from services.prd_workflow_generator_service import UnsupportedPrdWorkflowSourceError as ServiceUnsupportedSource


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


def test_from_prd_controller_forwards_valid_payload(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    api = module.PrdWorkflowGenerateApi()
    method = unwrap(api.post)
    captured: dict = {}

    monkeypatch.setattr(module, "enforce_rbac_access", lambda **kwargs: captured.setdefault("rbac", kwargs))

    def _generate(**kwargs):
        captured["service"] = kwargs
        return module.PrdWorkflowGenerateResponse.model_validate(
            {
                "result": "success",
                "draft_synced": False,
                "workflow": {"id": "workflow-1", "hash": "hash-1"},
                "source": {
                    "type": "wiki_tree_context",
                    "doc_id": "wiki-doc-1",
                    "workspace": "workspace-1",
                    "tree_type": "reasoning_action",
                    "force_rebuild": False,
                },
                "warnings": [],
                "missing_requirements": [],
                "graph": None,
            }
        )

    monkeypatch.setattr(module.PrdWorkflowGeneratorService, "generate_from_prd", _generate)

    with app.test_request_context("/console/api/workflow-generate/from-prd", method="POST", json=_payload()):
        response = method(api, SimpleNamespace(), "tenant-1", SimpleNamespace(id="account-1"))

    assert response["result"] == "success"
    assert captured["rbac"]["path_args"] == {"app_id": "app-1"}
    assert captured["rbac"]["tenant_id"] == "tenant-1"
    assert captured["rbac"]["account_id"] == "account-1"
    assert captured["service"]["tenant_id"] == "tenant-1"
    assert captured["service"]["payload"].source.tree_type == "reasoning_action"
    assert captured["service"]["payload"].source.force_rebuild is False


def test_from_prd_controller_missing_doc_id_raises_validation_error(app: Flask) -> None:
    api = module.PrdWorkflowGenerateApi()
    method = unwrap(api.post)
    raw = _payload()
    del raw["source"]["doc_id"]

    with app.test_request_context("/console/api/workflow-generate/from-prd", method="POST", json=raw):
        with pytest.raises(ValidationError):
            method(api, SimpleNamespace(), "tenant-1", SimpleNamespace(id="account-1"))


def test_from_prd_controller_maps_unsupported_source_error(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    api = module.PrdWorkflowGenerateApi()
    method = unwrap(api.post)

    monkeypatch.setattr(module, "enforce_rbac_access", lambda **_kwargs: None)

    def _raise(**_kwargs):
        raise ServiceUnsupportedSource("MVP only supports wiki_tree_context source.")

    monkeypatch.setattr(module.PrdWorkflowGeneratorService, "generate_from_prd", _raise)

    with app.test_request_context("/console/api/workflow-generate/from-prd", method="POST", json=_payload()):
        with pytest.raises(UnsupportedPrdWorkflowSourceError) as exc_info:
            method(api, SimpleNamespace(), "tenant-1", SimpleNamespace(id="account-1"))

    assert exc_info.value.error_code == "unsupported_prd_workflow_source"


def test_from_prd_controller_allows_service_to_reject_non_wiki_source(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = module.PrdWorkflowGenerateApi()
    method = unwrap(api.post)
    raw = _payload()
    raw["source"]["type"] = "text"

    monkeypatch.setattr(module, "enforce_rbac_access", lambda **_kwargs: None)
    monkeypatch.setattr(
        module.PrdWorkflowGeneratorService,
        "generate_from_prd",
        lambda **_kwargs: (_ for _ in ()).throw(ServiceUnsupportedSource("unsupported")),
    )

    with app.test_request_context("/console/api/workflow-generate/from-prd", method="POST", json=raw):
        with pytest.raises(UnsupportedPrdWorkflowSourceError):
            method(api, SimpleNamespace(), "tenant-1", SimpleNamespace(id="account-1"))
