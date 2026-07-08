"""Service for exporting published workflows as strict custom packages.

The package is generated lazily for a single download request. It is never
persisted and it is built only from the tenant-scoped published workflow
snapshot selected by the caller.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.workflow.prd_compiler.package_builder import WorkflowPackageArtifact, build_workflow_package_zip
from models import App
from services.errors.app import WorkflowNotFoundError
from services.workflow_service import WorkflowService


class WorkflowPackageService:
    """Build downloadable custom workflow packages from published snapshots."""

    def __init__(self, workflow_service: WorkflowService | None = None) -> None:
        self._workflow_service = workflow_service or WorkflowService()

    def export_published_workflow_package(
        self,
        *,
        session: Session,
        app_model: App,
        workflow_id: str,
    ) -> WorkflowPackageArtifact:
        """Return an in-memory ZIP artifact for a published workflow.

        ``WorkflowService.get_published_workflow_by_id`` enforces app and tenant
        scoping and rejects draft workflow versions, so this method does not
        need a second ownership check.
        """
        workflow = self._workflow_service.get_published_workflow_by_id(
            app_model=app_model,
            workflow_id=workflow_id,
            session=session,
        )
        if workflow is None:
            raise WorkflowNotFoundError("Workflow not found.")

        title = workflow.marked_name or app_model.name or "Workflow Package"
        scenario = workflow.marked_comment or getattr(app_model, "description", None) or ""
        return build_workflow_package_zip(
            package_id=f"{app_model.name or 'workflow'}-{workflow.id}",
            version=str(workflow.version or "0.1.0"),
            title=title,
            scenario=scenario,
            graph=workflow.graph_dict,
        )
