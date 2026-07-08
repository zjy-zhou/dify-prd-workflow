"""Console API for generating workflow drafts from PRD sources."""

from flask_restx import Resource
from sqlalchemy.orm import Session

from controllers.common.schema import register_response_schema_models, register_schema_models
from controllers.common.wraps import enforce_rbac_access
from controllers.console import console_ns
from controllers.console.app.error import AppNotFoundError, DraftWorkflowNotSync, UnsupportedPrdWorkflowSourceError
from controllers.console.app.wraps import with_session
from controllers.console.wraps import (
    RBACPermission,
    RBACResourceScope,
    account_initialization_required,
    edit_permission_required,
    setup_required,
    with_current_tenant_id,
    with_current_user,
)
from core.workflow.prd_compiler.entities import PrdWorkflowGeneratePayload, PrdWorkflowGenerateResponse
from libs.login import login_required
from models import Account
from services.errors.app import WorkflowHashNotEqualError
from services.prd_workflow_generator_service import (
    PrdWorkflowAppNotFoundError,
    PrdWorkflowGeneratorService,
    UnsupportedPrdWorkflowSourceError as ServiceUnsupportedPrdWorkflowSourceError,
)


register_schema_models(console_ns, PrdWorkflowGeneratePayload)
register_response_schema_models(console_ns, PrdWorkflowGenerateResponse)


@console_ns.route("/workflow-generate/from-prd")
class PrdWorkflowGenerateApi(Resource):
    """Create a workflow draft generation request from a supported PRD source."""

    @console_ns.doc("generate_workflow_from_prd")
    @console_ns.doc(description="Generate a Dify workflow draft from a PRD source")
    @console_ns.expect(console_ns.models[PrdWorkflowGeneratePayload.__name__])
    @console_ns.response(
        200,
        "PRD workflow generation request accepted",
        console_ns.models[PrdWorkflowGenerateResponse.__name__],
    )
    @console_ns.response(400, "Invalid request parameters or unsupported PRD source")
    @console_ns.response(403, "Permission denied")
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_current_tenant_id
    @edit_permission_required
    @with_session(write=True)
    def post(self, session: Session, current_tenant_id: str, current_user: Account):
        payload = PrdWorkflowGeneratePayload.model_validate(console_ns.payload or {})
        enforce_rbac_access(
            tenant_id=current_tenant_id,
            account_id=current_user.id,
            resource_type=RBACResourceScope.APP,
            scene=RBACPermission.APP_VIEW_LAYOUT,
            path_args={"app_id": payload.app_id},
        )

        try:
            result = PrdWorkflowGeneratorService.generate_from_prd(
                session=session,
                tenant_id=current_tenant_id,
                payload=payload,
                account=current_user,
            )
        except ServiceUnsupportedPrdWorkflowSourceError as exc:
            raise UnsupportedPrdWorkflowSourceError(str(exc)) from exc
        except PrdWorkflowAppNotFoundError as exc:
            raise AppNotFoundError() from exc
        except WorkflowHashNotEqualError as exc:
            raise DraftWorkflowNotSync() from exc

        return result.model_dump(mode="json")
