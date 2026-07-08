# PRD 到工作流生成阶段性交接文档

状态：阶段 0-3 已完成静态实现；阶段 2.4 第二阶段节点扩展已完成静态实现；真实端到端验收尚未完成
最后更新：2026-07-08

## 1. 使用方式

本文用于记录“Wiki PRD -> LLM 编译 -> Dify workflow draft -> 画布编辑调试 -> 发布 -> 严格格式 package 下载”各阶段实现的交接信息。每完成一个阶段，都应在对应章节补充：

- 实际完成内容。
- 关键决策和偏离原计划的地方。
- 修改或新增文件。
- 已验证命令和结果。
- 未验证项、阻塞项和风险。
- 下一阶段优先执行清单。

本文不是需求说明或技术方案的替代品。完整背景见：

- `docs/prd-to-workflow-requirements.md`
- `docs/prd-to-workflow-technical-design.md`
- `docs/prd-to-workflow-development-steps.md`
- `docs/prd-to-workflow-stage-0-code-map.md`

## 2. 全局目标和边界

目标是在 Dify 开源版内跑通从 Wiki PRD 到可运行 Dify 工作流的闭环，并在发布后按用户给定格式导出自定义 package。

已确认边界：

- 第一版基于 Dify 二次开发，不单独重建画布和运行时。
- MVP 只支持 Wiki PRD 来源。
- PRD 结构化上下文来自 Wiki Tree Context API。
- 后端生成并校验 Dify graph 后直接写入 draft，前端刷新画布。
- MVP 节点类型只支持 Start、LLM、IfElse、Answer/End。
- 发布仍走 Dify 原有 `/apps/{app_id}/workflows/publish`。
- package 只在用户下载时按需生成，不长期保存。
- package 顶层结构必须严格等于 `package.yaml`、`workflow.yaml`、`skills/`、`schemas/`、`data/`。
- Dify DSL、Dify graph、IR、validation、source metadata、完整 PRD 原文、完整 LLM prompt 不进入下载 package。
- 右侧自然语言助手使用独立 graph patch prompt，先预览，用户确认后应用。

## 3. 当前工件清单

已完成文档：

- `docs/prd-to-workflow-requirements.md`
- `docs/prd-to-workflow-technical-design.md`
- `docs/prd-to-workflow-development-steps.md`
- `docs/prd-to-workflow-stage-0-code-map.md`

已新增 fixture：

- `docs/fixtures/prd-to-workflow/minimal-advanced-chat-start-llm-answer.json`
- `docs/fixtures/prd-to-workflow/minimal-workflow-start-llm-end.json`

外部参考：

- Wiki Tree Context API 文档：`E:/2-项目资料/0-元策略编译器项目/4-接口数据及文档/wiki_tree_context_api.md`
- package 参考目录：`E:/2-项目资料/0-元策略编译器项目/1-prd_package/wig-opportunity-discovery/`

## 4. 阶段 0：开发准备和代码定位

当前状态：已完成静态代码定位；已完成最小 graph fixture JSON 语法验证；尚未完成真实 draft sync 验证。

### 目标

确认 Dify 当前 graph shape、draft sync 入参、发布流程和前端画布刷新方式，为阶段 1 的 PRD 编译和写入 draft 打底。

### 已完成

- 找出当前 workflow generator 输出的 graph JSON 结构。
- 找出 `WorkflowService.sync_draft_workflow` 参数、hash 校验方式和异常形态。
- 找出 draft 页面刷新 draft 的前端 hook 和事件方式。
- 找出 publish 后读取 published workflow 的方法。
- 找出 Start、LLM、IfElse、Answer/End 的最小合法 node data。
- 沉淀两个最小 graph fixture。

### 关键结论

- Dify graph 顶层结构是 `nodes`、`edges`、`viewport`。
- 节点是 ReactFlow node wrapper，真实节点类型在 `node.data.type`。
- 边是 ReactFlow edge wrapper，Dify 使用 `type: "custom"`。
- 普通 Workflow 终点是 `End`，Advanced Chat/Chatflow 终点是 `Answer`。
- HTTP draft sync 入参字段是 `graph`、`features`、`hash`、`environment_variables`、`conversation_variables`。
- `hash` 不匹配时后端返回 HTTP 409，错误码为 `draft_workflow_not_sync`。
- 后端直接写入 draft 后，前端优先调用 `handleRefreshWorkflowDraft()` 重新拉取并刷新画布。

### 关键代码定位

后端：

- `api/controllers/console/app/generator.py`
- `api/services/workflow_generator_service.py`
- `api/core/workflow/generator/`
- `api/controllers/console/app/workflow.py`
- `api/controllers/console/app/error.py`
- `api/services/workflow_service.py`
- `api/services/errors/app.py`

前端：

- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/types.ts`
- `web/app/components/workflow/workflow-generator/`
- `web/app/components/workflow/workflow-generator/apply.ts`
- `web/app/components/workflow/hooks/use-workflow-update.ts`
- `web/app/components/workflow/hooks/use-workflow-refresh-draft.ts`
- `web/app/components/workflow-app/hooks/use-workflow-refresh-draft.ts`
- `web/service/workflow.ts`
- `web/service/use-workflow.ts`
- `web/service/debug.ts`
- `web/app/components/workflow/nodes/start/default.ts`
- `web/app/components/workflow/nodes/llm/default.ts`
- `web/app/components/workflow/nodes/if-else/default.ts`
- `web/app/components/workflow/nodes/answer/default.ts`
- `web/app/components/workflow/nodes/end/default.ts`

### 已验证

已验证 fixture JSON 语法：

```powershell
python -m json.tool docs\fixtures\prd-to-workflow\minimal-advanced-chat-start-llm-answer.json
python -m json.tool docs\fixtures\prd-to-workflow\minimal-workflow-start-llm-end.json
```

### 未验证和阻塞

- 尚未执行 `WorkflowGenerator._validate_structure(...)`。
- 尚未用真实 `POST /console/api/apps/{app_id}/workflows/draft` 验证 fixture 写入。
- 尚未用真实 provider/name 执行 draft debug。
- 当时阻塞原因：
  - 系统 Python 缺少 `json_repair`。
  - 本机 PATH 中没有 `uv`。
  - Docker Desktop daemon 未运行。

### 交接给阶段 1 的动作

1. 用当前两个 fixture 作为 Dify graph compiler 的最小模板。
2. 后端写 draft 必须复用 `WorkflowService.sync_draft_workflow`。
3. 写入前必须做 graph validator，失败时不得修改 draft。
4. 前端生成成功后调用 `handleRefreshWorkflowDraft()`，以服务端 draft 为准刷新画布。
5. 优先补真实环境验证：fixture -> draft sync -> draft debug。

## 5. 阶段 1：Dify Draft 生成 MVP

当前状态：进行中；阶段 1.1“增加后端配置和请求模型”已完成。

### 阶段目标

输入合法 Wiki workspace 和 doc id 后，后端调用 Wiki Tree Context API，LLM 生成 Workflow IR，IR 编译为 Dify graph，校验通过后写入 Dify draft，前端刷新画布。

### 范围

必须支持：

- Wiki PRD 来源。
- 阻塞式生成接口 `POST /console/api/workflow-generate/from-prd`。
- Workflow IR。
- IR validator。
- IR -> Dify graph compiler。
- Graph validator。
- Draft sync。
- 前端 PRD 生成入口和画布刷新。

暂不支持：

- 文件上传 PRD。
- 粘贴文本 PRD。
- Coze DSL 或 Coze 运行。
- 第二阶段节点。
- package 下载。
- 右侧自然语言编辑。

### 建议新增或修改文件

后端：

- `api/controllers/console/app/prd_workflow_generator.py`
- `api/controllers/console/app/generator.py`
- `api/services/prd_context_service.py`
- `api/services/prd_workflow_generator_service.py`
- `api/core/workflow/prd_compiler/entities.py`
- `api/core/workflow/prd_compiler/wiki_context.py`
- `api/core/workflow/prd_compiler/planner.py`
- `api/core/workflow/prd_compiler/dify_compiler.py`
- `api/core/workflow/prd_compiler/validator.py`
- `api/core/workflow/prd_compiler/prompts/prd_to_workflow_ir.md`

前端：

- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/workflow-generator/`
- `web/service/debug.ts`
- `web/service/use-workflow.ts`
- `web/i18n/en-US/`
- 其他 locale 文件。

### 实现交接模板

阶段完成后补充：

- 实际 API 路径、请求体、响应体。
- Wiki context service 的配置项名称和 timeout。
- LLM 调用方式，是否复用 Dify provider/model 配置。
- IR model 字段和支持的 `phase.kind`。
- Graph validator 校验项。
- Draft hash 冲突处理方式。
- 前端刷新 draft 的 hook 或 query key。
- 新增测试文件和测试命令。

### 阶段验收

- 给定合法 Wiki `doc_id` 能生成 Dify workflow draft。
- 生成后的 draft 能在画布正常打开。
- 支持节点能完成一次基础 debug 运行。
- Wiki API、LLM、IR、graph 任一失败时 draft 不被修改。
- draft hash 冲突时返回明确错误。

### 重点风险

- Dify graph node data 字段与当前版本不完全匹配。
- IfElse 的 branch handle 和 variable selector 不完整。
- LLM 输出不稳定，必须经过 JSON parse 和 IR validator。
- 外部 Wiki API 响应过大，需要裁剪并返回 warning。
- 覆盖用户 draft，需要 hash 和前端确认保护。

### 阶段 1.1 交接：后端配置和请求模型

完成时间：2026-07-07

本次完成范围：

- 新增阻塞式接口 `POST /console/api/workflow-generate/from-prd`。
- 新增严格 Pydantic v2 请求模型：
  - `app_id`
  - `source.type`
  - `source.doc_id`
  - `source.workspace`
  - `source.tree_type`，默认 `reasoning_action`
  - `source.force_rebuild`，默认 `false`
  - `model_config`
  - `sync_to_draft`，默认 `true`
  - `overwrite_policy`，默认 `require_confirmation`
  - `draft_hash`
- `source`、`model_config` 和顶层 payload 均使用 `extra="forbid"`。
- `source.type` 非 `wiki_tree_context` 不在 DTO 层拒绝，而是在 service 层返回稳定业务错误，方便后续扩展其他 source。
- controller 只做 payload 解析、显式 RBAC 鉴权、调用 service 和响应序列化。
- service 当前只做 MVP source 校验、tenant-scoped app 查询、draft workflow 上下文读取；不调用 Wiki、不调用 LLM、不写 draft。
- 新增 `PrdContextService` 占位边界，后续用于接入 Wiki Tree Context API。

涉及文件：

- `api/core/workflow/prd_compiler/__init__.py`
- `api/core/workflow/prd_compiler/entities.py`
- `api/controllers/console/app/prd_workflow_generator.py`
- `api/controllers/console/app/error.py`
- `api/controllers/console/__init__.py`
- `api/services/prd_context_service.py`
- `api/services/prd_workflow_generator_service.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_entities.py`
- `api/tests/unit_tests/services/test_prd_workflow_generator_service.py`
- `api/tests/unit_tests/controllers/console/app/test_prd_workflow_generator_api.py`

关键实现决策：

- 由于新接口的 `app_id` 在 body 中，不在 URL path 中，现有 `@rbac_permission_required` 无法直接从 path args 提取资源 id；controller 改为解析 payload 后显式调用 `enforce_rbac_access(..., path_args={"app_id": payload.app_id})`。
- service 通过 SQLAlchemy `select(App)` 查询 app，条件包含 `App.id`、`App.tenant_id`、`App.status == "normal"`、`App.mode in [workflow, advanced-chat]`，确保 DB 查询按 tenant scope。
- 当前响应为合同占位成功响应：`draft_synced=false`，返回当前 draft 的 `workflow.id/hash`，并带 warning `PRD workflow compilation is not implemented in this stage.`。
- HTTP 业务错误 `unsupported_prd_workflow_source` 已加入 `controllers.console.app.error`。
- 请求体不暴露额外 `mode` 字段；后续 graph 形态由 `app_id` 对应的 Dify App 模式推断，避免调用方传入值与实际 App 模式冲突。

已验证：

```powershell
python -m py_compile api\core\workflow\prd_compiler\__init__.py api\core\workflow\prd_compiler\entities.py api\services\prd_context_service.py api\services\prd_workflow_generator_service.py api\controllers\console\app\prd_workflow_generator.py api\tests\unit_tests\core\workflow\prd_compiler\test_entities.py api\tests\unit_tests\services\test_prd_workflow_generator_service.py api\tests\unit_tests\controllers\console\app\test_prd_workflow_generator_api.py
```

结果：通过。

2026-07-07 复验：

```powershell
py -3.13 -m py_compile api\core\workflow\prd_compiler\__init__.py api\core\workflow\prd_compiler\entities.py api\services\prd_context_service.py api\services\prd_workflow_generator_service.py api\controllers\console\app\prd_workflow_generator.py api\tests\unit_tests\core\workflow\prd_compiler\test_entities.py api\tests\unit_tests\services\test_prd_workflow_generator_service.py api\tests\unit_tests\controllers\console\app\test_prd_workflow_generator_api.py
```

结果：通过。PyCharm 当前 `Python 3.13` SDK 指向全局解释器 `C:/Users/众维/AppData/Local/Programs/Python/Python313/python.exe`，该解释器未安装 `pytest` 和 `pydantic`，因此目标 pytest 仍未完成。另尝试 Docker API 容器复验，但 Docker daemon 未运行。

尝试但未完成的验证：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONPATH='api'; python -c "from core.workflow.prd_compiler.entities import PrdWorkflowGeneratePayload; ..."
```

结果：当前 `python` 是 3.11.9，项目代码依赖 Python 3.12+ 的 `typing.override`，导入 `api/configs/app_config.py` 时失败；未进入 DTO 行为验证。

```powershell
pytest api/tests/unit_tests/core/workflow/prd_compiler/test_entities.py api/tests/unit_tests/services/test_prd_workflow_generator_service.py api/tests/unit_tests/controllers/console/app/test_prd_workflow_generator_api.py
```

结果：未进入新增测试，当前 `python` 是 3.11.9，仓库代码使用 Python 3.12+ 语法，加载 conftest 时在 `api/core/workflow/node_factory.py` 报 `SyntaxError: invalid syntax`。

```powershell
py -3.13 -m pytest api/tests/unit_tests/core/workflow/prd_compiler/test_entities.py api/tests/unit_tests/services/test_prd_workflow_generator_service.py api/tests/unit_tests/controllers/console/app/test_prd_workflow_generator_api.py
```

结果：Python 3.13 可用，但没有安装 pytest，报 `No module named pytest`。

```powershell
py -3.13 -c "from core.workflow.prd_compiler.entities import PrdWorkflowGeneratePayload; ..."
```

结果：Python 3.13 可用，但没有安装 pydantic，报 `No module named 'pydantic'`。

后续必须补跑：

- 在符合 `api/pyproject.toml` 的 Python `~=3.12.0` + dev dependencies 环境中运行新增单元测试。
- 确认 `/console/api/workflow-generate/from-prd` 路由在 Flask app 启动后可见。
- 进入阶段 1.2 前，决定是否安装/恢复 `uv`，按仓库约定使用 `uv run --project api ...` 跑测试。

下一步：

1. 接入 Wiki Tree Context API，完善 `PrdContextService`。
2. 定义 PRD context 标准化模型和错误形态。
3. 保持失败不写 draft 的原则。

### 阶段 1.2 交接：Wiki context 标准化输入

完成时间：2026-07-08

本次完成范围：
- 新增 Wiki Tree Context API 配置项：
  - `PRD_WIKI_TREE_CONTEXT_BASE_URL`
  - `PRD_WIKI_TREE_CONTEXT_TIMEOUT`
- 新增 `PrdWikiContext` 标准化模型，作为后续 PRD compiler/LLM planner 的输入。
- 新增 Wiki API 响应标准化逻辑，读取并归一化：
  - `tree_json`
  - `outline_md`
  - `dimension_bundle.markdown`
  - `raw_bundle.markdown`
  - `source_name`
  - `version`
  - `tree_type`
- 大文档裁剪策略：
  - `tree_json` 超预算时优先保留 `action`、`condition`、`outcome`、`rule` 节点。
  - `raw_bundle.markdown` 不默认完整进入 compiler 输入，只保留 `raw_markdown_excerpt`。
  - `outline_md`、`dimension_bundle.markdown`、`raw_bundle.markdown` 被裁剪时写入 `warnings`。
- `PrdContextService` 调用外部接口：
  - `POST {PRD_WIKI_TREE_CONTEXT_BASE_URL}/api/wiki/tree/context`
  - Header：`LIGHTRAG-WORKSPACE: <workspace_id>`
  - Body：`doc_id`、`tree_type`、`force_rebuild`
  - 出站 HTTP 走 `core.helper.ssrf_proxy.post`
  - 显式设置 `httpx.Timeout(...)`
- `PrdWorkflowGeneratorService.generate_from_prd(...)` 已接入 Wiki context resolution。
  - Wiki 失败时返回 `result="failed"`、`draft_synced=false`。
  - 错误可读信息进入 `warnings`。
  - 机器可判断错误码进入 `missing_requirements`。
  - 当前阶段仍不调用 LLM、不编译 graph、不写 draft。

涉及文件：
- `api/configs/feature/__init__.py`
- `api/core/workflow/prd_compiler/wiki_context.py`
- `api/services/prd_context_service.py`
- `api/services/prd_workflow_generator_service.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_wiki_context.py`
- `api/tests/unit_tests/services/test_prd_context_service.py`
- `api/tests/unit_tests/services/test_prd_workflow_generator_service.py`

关键实现决策：
- Wiki API base URL 不写死在代码中，必须通过 Dify config 注入。
- 外部 HTTP 调用使用 SSRF proxy，且本服务显式传入 timeout。
- context 标准化放在 `core.workflow.prd_compiler.wiki_context`，HTTP 调用放在 `services.prd_context_service`。
- 失败路径不抛到 draft sync，也不修改 draft；generator service 只返回失败响应。
- raw PRD 原文不作为默认完整 LLM 输入，避免大文档和企业数据泄露风险。

新增测试覆盖：
- Wiki API 正常响应可标准化为 `PrdWikiContext`。
- 缺少 `tree_json` 时失败，错误包含 `tree_json`。
- 外部 API 500 可映射为 `wiki_context_server_error`。
- 外部 API 401/403 可映射为 `wiki_context_forbidden`。
- 外部 API timeout 可映射为 `wiki_context_timeout`。
- 超大 `raw_bundle.markdown` 会生成 warning 并只保留 excerpt。
- 超大 `tree_json` 会优先保留 `rule/action/condition/outcome` 等节点。
- generator service 在 Wiki context 失败时返回 `draft_synced=false`。

已验证：

```powershell
py -3.13 -m py_compile api\configs\feature\__init__.py api\core\workflow\prd_compiler\wiki_context.py api\services\prd_context_service.py api\services\prd_workflow_generator_service.py api\tests\unit_tests\core\workflow\prd_compiler\test_wiki_context.py api\tests\unit_tests\services\test_prd_context_service.py api\tests\unit_tests\services\test_prd_workflow_generator_service.py
```

结果：通过。

尝试但未完成的验证：

```powershell
py -3.13 -m pytest api/tests/unit_tests/core/workflow/prd_compiler/test_wiki_context.py api/tests/unit_tests/services/test_prd_context_service.py api/tests/unit_tests/services/test_prd_workflow_generator_service.py api/tests/unit_tests/core/workflow/prd_compiler/test_entities.py api/tests/unit_tests/controllers/console/app/test_prd_workflow_generator_api.py
```

结果：当前 PyCharm `Python 3.13` SDK 指向全局解释器 `C:/Users/众维/AppData/Local/Programs/Python/Python313/python.exe`，该解释器未安装 `pytest`，报 `No module named pytest`。另外仓库 `api/pyproject.toml` 声明 `requires-python = "~=3.12.0"`，正式测试仍建议使用 Python 3.12 环境。

后续必须补跑：
- 在符合 `api/pyproject.toml` 的 Python 3.12 + dev dependencies 环境中运行新增 pytest。
- 配置真实 `PRD_WIKI_TREE_CONTEXT_BASE_URL` 后，用真实 Wiki API 验证 200、401/403、500、timeout 场景。
- 进入下一阶段：LLM planner 输出 Workflow IR，失败仍不得写 draft。

### 阶段 1.3 交接：Workflow IR 和 IR 校验

完成时间：2026-07-08

本次完成范围：
- 在 `api/core/workflow/prd_compiler/entities.py` 中新增平台无关 Workflow IR 模型：
  - `WorkflowIR`
  - `WorkflowIRVariable`
  - `WorkflowIRPhase`
  - `WorkflowIREdge`
  - `WorkflowIRSchema`
  - `WorkflowIRSkill`
  - `WorkflowIRConfirmation`
  - `WorkflowIRValidationResult`
- MVP phase kind 白名单：
  - `workflow_start`
  - `llm_task`
  - `condition`
  - `workflow_output`
- 新增 `api/core/workflow/prd_compiler/validator.py`，提供 `validate_workflow_ir(...)`。
- 校验规则：
  - workflow 至少有一个 input。
  - workflow 至少有一个 output。
  - workflow 至少有一个 phase。
  - phase id 必须唯一。
  - edge source/target 必须引用已存在 phase。
  - 第二阶段节点 kind（如 `http_call`、`code_transform`）进入 `warnings` 和 `missing_requirements`，并使结果不可继续编译。

涉及文件：
- `api/core/workflow/prd_compiler/entities.py`
- `api/core/workflow/prd_compiler/validator.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_ir_validator.py`

关键实现决策：
- IR 的 `phase.kind` 使用字符串字段，而不是直接用 enum 限死；这样 LLM 输出第二阶段节点时可以被解析出来并返回 unsupported warning。
- unsupported kind 不作为 Pydantic shape 错误，而作为语义校验结果中的 `missing_requirements`。
- `is_valid=false` 的 IR 不应进入 Dify graph compiler 或 draft sync。
- `confirmation` 语义先保留在 IR 中，MVP 不强制映射到 Dify graph。

新增测试覆盖：
- 合法 IR 校验通过。
- 重复 phase id 校验失败。
- edge 指向不存在 phase 校验失败。
- `http_call` 等第二阶段节点返回 unsupported missing requirement。
- 缺少 input/output 校验失败。

已验证：

```powershell
python -c "<line length check for new IR files>"
py -3.13 -m py_compile api\core\workflow\prd_compiler\entities.py api\core\workflow\prd_compiler\validator.py api\tests\unit_tests\core\workflow\prd_compiler\test_ir_validator.py
```

结果：通过。

尝试但未完成的验证：

```powershell
py -3.13 -m pytest api/tests/unit_tests/core/workflow/prd_compiler/test_ir_validator.py
```

结果：当前 PyCharm `Python 3.13` SDK 指向全局解释器 `C:/Users/众维/AppData/Local/Programs/Python/Python313/python.exe`，该解释器未安装 `pytest`，报 `No module named pytest`。正式测试仍需 Python 3.12 + dev dependencies 环境。

后续必须补跑：
- 在 Python 3.12 项目环境中运行 `test_ir_validator.py`。
- 下一阶段 LLM planner 必须先输出 `WorkflowIR`，并调用 `validate_workflow_ir(...)` 后才能继续 graph 编译。

### 阶段 1.4 交接：LLM Planner 输出 Workflow IR

完成时间：2026-07-08

本次完成范围：
- 新增 `api/core/workflow/prd_compiler/prompts/prd_to_workflow_ir.md`。
- 新增 `api/core/workflow/prd_compiler/planner.py`。
- 新增 `WorkflowIRPlanningResult`。
- `PrdWorkflowGeneratorService.generate_from_prd(...)` 已接入：
  - Wiki context 成功后解析 Dify model config。
  - 调用 `PrdWorkflowPlanner.plan(...)`。
  - planner 输出必须解析成 `WorkflowIR`。
  - planner 输出必须通过 `validate_workflow_ir(...)` 后续才可进入 graph 编译。
- 当前阶段仍不生成 Dify graph、不写 draft。

涉及文件：
- `api/core/workflow/prd_compiler/entities.py`
- `api/core/workflow/prd_compiler/planner.py`
- `api/core/workflow/prd_compiler/prompts/prd_to_workflow_ir.md`
- `api/services/prd_workflow_generator_service.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_planner.py`
- `api/tests/unit_tests/services/test_prd_workflow_generator_service.py`

关键实现决策：
- PRD planner 是独立 core 模块，不复用现有 workflow generator 私有方法，避免依赖 Dify graph 生成器内部实现。
- LLM prompt 明确只允许输出 JSON object，不允许 Markdown/prose。
- LLM 输出用 `json_repair.loads(...)` 解析，并在 JSON 解析失败时追加一次用户提示重试。
- Pydantic shape 错误映射为 `workflow_ir_invalid_shape`。
- 非 JSON 输出映射为 `workflow_ir_invalid_json`。
- 语义校验失败时，service 返回 `result="failed"`、`draft_synced=false`，不写 draft。

新增测试覆盖：
- mock LLM 输出合法 IR 后返回 validated planning result。
- mock LLM 连续输出非 JSON 时返回 `workflow_ir_invalid_json`。
- mock LLM 输出缺字段 IR 时返回 `workflow_ir_invalid_shape`。
- mock LLM 输出 `http_call` 等 unsupported kind 时，validation 返回 `unsupported_phase_kind:http_call`。
- generator service 在 planner JSON 失败时返回 `draft_synced=false`。
- generator service 在 IR validation 失败时返回 `draft_synced=false`。

已验证：

```powershell
python -c "<line length check for planner and service files>"
py -3.13 -m py_compile api\core\workflow\prd_compiler\entities.py api\core\workflow\prd_compiler\validator.py api\core\workflow\prd_compiler\planner.py api\services\prd_workflow_generator_service.py api\tests\unit_tests\core\workflow\prd_compiler\test_ir_validator.py api\tests\unit_tests\core\workflow\prd_compiler\test_planner.py api\tests\unit_tests\services\test_prd_workflow_generator_service.py
```

结果：通过。

尝试但未完成的验证：

```powershell
py -3.13 -m pytest api/tests/unit_tests/core/workflow/prd_compiler/test_planner.py api/tests/unit_tests/core/workflow/prd_compiler/test_ir_validator.py api/tests/unit_tests/services/test_prd_workflow_generator_service.py
```

结果：当前 Python 3.13 全局解释器未安装 `pytest`，报 `No module named pytest`。正式测试仍需 Python 3.12 + dev dependencies 环境。

后续必须补跑：
- 在 Python 3.12 项目环境中运行 planner、IR validator、PRD generator service 单测。
- 下一阶段实现 `WorkflowIR -> Dify graph` compiler，并在 graph validator 通过前继续禁止写 draft。

### 阶段 1.5 交接：Workflow IR 到 Dify Graph 编译器

完成时间：2026-07-08

本次完成范围：
- 新增 `api/core/workflow/prd_compiler/dify_compiler.py`。
- 新增 `compile_workflow_ir_to_dify_graph(...)`，把平台无关 `WorkflowIR` 编译为 Dify draft sync 可接收的 ReactFlow graph JSON。
- MVP 支持节点：
  - `workflow_start` -> Dify `start`
  - `llm_task` -> Dify `llm`
  - `condition` -> Dify `if-else`
  - `workflow_output` -> Dify `end` 或 `answer`
- 终点节点根据目标 App mode 推断：
  - `workflow` 生成 `end`
  - `advanced-chat` 生成 `answer`
- 节点 id 基于 IR phase id 稳定生成，并处理重复 slug。
- 坐标按拓扑层级生成，IfElse true/false 分支做上下错位，避免节点完全重叠。
- Start 节点根据 IR inputs 生成 Dify 输入变量。
- LLM 节点根据请求 `model_config` 生成 `model`、`prompt_template`、`variables`、`context`、`vision`。
- IfElse 节点支持从 `phase.config.conditions` 生成条件；未提供时使用第一个输入变量的 `not empty` 默认条件。
- Answer/End 节点引用上游 LLM `text` 或 Start 输入 selector。
- 新增 `DifyGraphValidationResult`。
- 在 `api/core/workflow/prd_compiler/validator.py` 中新增 `validate_dify_graph(...)`。

Graph validator 当前校验项：
- graph 至少包含一个 node。
- 有且只有一个 Start。
- 至少一个 Answer/End。
- node id 唯一。
- edge source/target 必须存在。
- MVP 节点类型白名单：`start`、`llm`、`if-else`、`answer`、`end`。
- LLM 节点必须包含 `model.provider`、`model.name`、`model.mode` 和 `prompt_template`。
- Start、LLM、IfElse、End、Answer 中的 selector 必须指向已知输出。
- IfElse 每个 case 和默认 false 分支都必须有 outgoing edge。

涉及文件：
- `api/core/workflow/prd_compiler/entities.py`
- `api/core/workflow/prd_compiler/dify_compiler.py`
- `api/core/workflow/prd_compiler/validator.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_dify_compiler.py`

关键实现决策：
- Dify graph adapter 返回普通 `dict[str, Any]`，不把 ReactFlow graph 全量 Pydantic 化，避免和 Dify 内部 graph shape 漂移时产生双重 schema 维护成本。
- Dify graph 编译器放在 `prd_compiler` 内，但不依赖 Flask、DB、service，保留未来抽离成 Dify adapter 的边界。
- Start selector 不假定节点 id 必然是 `start`，而是使用 phase id 到 node id 的真实映射。
- IfElse edge 的 `sourceHandle` 使用 `true`/`false`，与 Dify 现有 fixture 保持一致。
- 第二阶段节点仍不进入 graph compiler，继续在 IR validator 阶段被拒绝。

新增测试覆盖：
- 单链路 IR 可编译为 `Start -> LLM -> End`。
- 条件 IR 可编译为包含 `IfElse`、`true`/`false` 分支和 `Answer` 的 advanced-chat graph。
- graph validator 拒绝缺少 terminal 的 graph。
- graph validator 拒绝 edge 指向不存在 node 的 graph。

已验证：

```powershell
py -3.13 -m py_compile api\core\workflow\prd_compiler\entities.py api\core\workflow\prd_compiler\dify_compiler.py api\core\workflow\prd_compiler\validator.py api\services\prd_workflow_generator_service.py api\controllers\console\app\prd_workflow_generator.py api\tests\unit_tests\core\workflow\prd_compiler\test_dify_compiler.py api\tests\unit_tests\services\test_prd_workflow_generator_service.py
```

结果：通过。

线长检查：

```powershell
$files = @('api/core/workflow/prd_compiler/dify_compiler.py','api/core/workflow/prd_compiler/validator.py','api/services/prd_workflow_generator_service.py','api/tests/unit_tests/core/workflow/prd_compiler/test_dify_compiler.py','api/tests/unit_tests/services/test_prd_workflow_generator_service.py'); foreach ($file in $files) { $i=0; Get-Content -Encoding utf8 $file | ForEach-Object { $i++; if ($_.Length -gt 120) { "${file}:${i}:$($_.Length)" } } }
```

结果：无超过 120 字符行。

未验证项：
- 仍未运行 pytest，原因同前：当前全局 Python 3.13 环境缺少 `pytest`，仓库正式要求 Python `~=3.12.0`。
- 尚未用真实 Dify draft sync 验证生成 graph。
- IfElse 条件只实现 MVP 常用 shape，复杂多条件和嵌套条件需要后续真实 PRD 样例校准。

下一步：
1. 将编译和 graph validator 接入 `PrdWorkflowGeneratorService`。
2. graph 校验通过后调用 `WorkflowService.sync_draft_workflow`。
3. 对 draft hash 冲突做前置保护。

### 阶段 1.6 交接：接入 Draft Sync

完成时间：2026-07-08

本次完成范围：
- `PrdWorkflowGeneratorService.generate_from_prd(...)` 主链路已串联：
  1. tenant-scoped app 查询。
  2. draft hash 前置冲突检查。
  3. Wiki context 获取。
  4. Dify model config 解析。
  5. LLM planner 生成 `WorkflowIR`。
  6. IR validation。
  7. IR -> Dify graph compile。
  8. graph validation。
  9. 可选 draft sync。
- controller 已传入当前 `Account`，用于 draft sync 的 `created_by/updated_by`。
- controller 将 `WorkflowHashNotEqualError` 映射为已有 HTTP 409 `draft_workflow_not_sync`。
- 生成成功并写入 draft 后，响应返回：
  - `result="success"`
  - `draft_synced=true`
  - `workflow.id`
  - `workflow.hash`
  - `warnings`
  - `missing_requirements=[]`
  - graph summary：`node_count`、`edge_count`、`node_types`
- `sync_to_draft=false` 时只返回 graph summary，不写 draft。
- 写 draft 时尽量保留现有 draft 的：
  - `normalized_features_dict`
  - `environment_variables`
  - `conversation_variables`
- 如果没有现有 draft，则使用空 features 和空变量，由 Dify 原有 `validate_features_structure` 补默认结构。

涉及文件：
- `api/controllers/console/app/prd_workflow_generator.py`
- `api/services/prd_workflow_generator_service.py`
- `api/tests/unit_tests/services/test_prd_workflow_generator_service.py`

关键实现决策：
- `draft_hash` 不匹配时，在 Wiki/LLM 外部调用之前直接抛 `WorkflowHashNotEqualError`，减少成本并保护用户草稿。
- graph validation 失败、compile 失败、planner 失败、Wiki 失败都返回 `draft_synced=false`，不调用 draft sync。
- draft sync 异常会返回 `draft_sync_failed`，并保留 graph summary 方便定位；hash 冲突仍走标准 409。
- response 不返回完整 graph，只返回 summary；前端成功后应 refetch draft，以服务端 draft 为准刷新画布。

新增测试覆盖：
- 成功路径会调用 fake `sync_draft_workflow`，响应 `draft_synced=true`，并返回新 workflow hash。
- draft hash 冲突会在 Wiki context 调用前抛 `WorkflowHashNotEqualError`。
- Wiki context 失败、planner JSON 失败、IR validation 失败仍返回 `draft_synced=false`。

已验证：

```powershell
py -3.13 -m py_compile api\tests\unit_tests\services\test_prd_workflow_generator_service.py api\core\workflow\prd_compiler\dify_compiler.py api\core\workflow\prd_compiler\validator.py api\services\prd_workflow_generator_service.py
```

结果：通过。

清理：
- 已删除本次 `py_compile` 生成的相关 `__pycache__` 目录：
  - `api/core/workflow/prd_compiler/__pycache__`
  - `api/services/__pycache__`
  - `api/controllers/console/app/__pycache__`
  - `api/tests/unit_tests/core/workflow/prd_compiler/__pycache__`
  - `api/tests/unit_tests/services/__pycache__`

未验证项：
- 仍未运行 pytest，需 Python 3.12 + dev dependencies 环境。
- 尚未在真实浏览器/真实 Dify 应用中验证 `POST /console/api/workflow-generate/from-prd` 写入 draft 后画布刷新。
- `WorkflowService.sync_draft_workflow` 内部仍使用 Dify 既有 `db.session`，本接口 controller 已改为 write session，但后续如要彻底统一事务边界，需要更大范围迁移。

下一步：
1. 实现阶段 1.7：前端 PRD 生成入口，成功后 refetch draft。
2. 配置真实 `PRD_WIKI_TREE_CONTEXT_BASE_URL` 和模型 provider 后做端到端人工验收。
3. 阶段 1 通过后再进入 package builder。

### 阶段 1.7 交接：前端 PRD 生成入口

完成时间：2026-07-08

本次完成范围：
- 新增 `web/app/components/workflow/prd-workflow-generator/`，在 workflow 编辑页 header 提供 Wiki PRD 生成入口。
- 新增前端请求类型与调用函数 `generateWorkflowFromPrd(...)`：
  - 文件：`web/service/debug.ts`
  - 路径：`POST /console/api/workflow-generate/from-prd`
- 表单支持：
  - Wiki workspace
  - Wiki doc id
  - tree type，默认 `reasoning_action`
  - force rebuild
  - 复用 workflow generator 的模型配置存储和模型参数弹窗
- 生成前会调用 `flushPendingSync()`，再弹出覆盖当前 draft 的二次确认。
- 请求体携带当前 `draft_hash`，与后端 hash 冲突保护配合。
- 生成成功且 `draft_synced=true` 后调用 `handleRefreshWorkflowDraft()`，以前端重新拉取服务端 draft 作为画布刷新来源。
- 已补齐所有 `web/i18n/*/workflow.json` 中的 `prdWorkflowGenerator.*` 文案键。
- 收尾修复：`model_config.mode` 现在使用 `EMPTY_WORKFLOW_GENERATOR_MODEL.mode` 兜底，避免前端类型层出现 `undefined`。

涉及文件：
- `web/app/components/workflow/prd-workflow-generator/index.tsx`
- `web/app/components/workflow/prd-workflow-generator/README.md`
- `web/app/components/workflow-app/components/workflow-header/index.tsx`
- `web/service/debug.ts`
- `web/i18n/*/workflow.json`

关键实现决策：
- 前端成功响应不直接消费完整 graph，而是 refetch draft，让 Dify 现有画布以服务端 draft 为准重新渲染。
- 覆盖用户 draft 必须有显式确认；hash 冲突由后端标准 `draft_workflow_not_sync` 处理。
- `source.type` 第一版固定为 `wiki_tree_context`，不暴露文件上传或文本粘贴入口。

已验证：
```powershell
node -e "const fs=require('fs'); const path=require('path'); for (const locale of fs.readdirSync('web/i18n')) { const file=path.join('web/i18n', locale, 'workflow.json'); if (fs.existsSync(file)) JSON.parse(fs.readFileSync(file,'utf8')); }"
```

结果：通过，所有 `workflow.json` 可解析。

未验证项：
- `pnpm --dir web type-check` 尚未完成；本地 `web/node_modules` 不存在，此前尝试安装依赖时网络出现 `ECONNRESET/ETIMEDOUT`。
- 尚未在真实浏览器中完成“点击 PRD -> 输入 Wiki 信息 -> 后端生成 -> 画布刷新”的人工验收。
- 尚未接入真实 Wiki API 和真实 Qwen/GPT 模型做端到端效果校准。

阶段 1 当前状态：
- 后端 1.1 到 1.6 已完成静态实现。
- 前端 1.7 已完成静态实现。
- 阶段 1 还缺真实环境端到端验收与正式 pytest/type-check。

## 6. 阶段 2：Package 下载和更多节点

当前状态：Package builder、Package export API、前端下载入口已完成静态实现；第二阶段更多节点扩展尚未启动。

### 阶段目标

发布后可按需导出严格格式 package；在 Dify 路径稳定后逐步支持更多节点。

### 范围优先级

优先实现 package 下载，再扩展节点。原因是 package 格式是发布闭环的必要输出，且用户已要求严格遵守参考 package 格式。

### 建议新增或修改文件

后端：

- `api/services/workflow_package_service.py`
- `api/core/workflow/prd_compiler/package_builder.py`
- `api/controllers/console/app/workflow.py`
- `api/controllers/console/app/prd_workflow_generator.py`

前端：

- `web/service/use-workflow.ts`
- workflow 发布成功区域或 workflow 操作菜单相关组件。
- `web/i18n/en-US/`

### Package 强约束

允许的顶层结构仅为：

```text
package.yaml
workflow.yaml
skills/
schemas/
data/
```

禁止进入 package：

- Dify DSL。
- Dify graph。
- IR。
- validation。
- source metadata。
- 完整原始 PRD。
- 完整 LLM prompt。
- 真实密钥、凭证、API Key。
- 任何未在 package 标准中声明的额外顶层文件或目录。

### 节点扩展顺序

建议顺序：

1. Knowledge Retrieval。
2. HTTP Request。
3. Code。
4. Tool。
5. Human Input。
6. Trigger。

每扩一种节点，都要同步更新：

- IR kind 白名单。
- LLM prompt。
- IR validator。
- Dify graph compiler。
- Graph validator。
- Package builder。
- 前端展示和错误提示。
- 单元测试 fixture。

### 实现交接模板

阶段完成后补充：

- Package export API 路径和返回形式。
- zip stream 生成方式。
- package.yaml/workflow.yaml 实际字段。
- skill.md front matter 实际字段。
- schema 生成规则。
- secret scan 或脱敏规则。
- 已支持的第二阶段节点列表。
- 每个新增节点对应的 Dify graph 最小 data。
- 新增测试和验收命令。

### 阶段验收

- 已发布 workflow 可下载 package。
- package 顶层结构严格符合允许列表。
- package 中不包含 Dify DSL、Dify graph、IR、validation、source metadata、完整 PRD 原文和密钥。
- YAML、JSON Schema、skill front matter 可解析。
- 新增节点至少逐项通过 graph sync 和基础 debug。

### 阶段 2.1 交接：严格格式 Package Builder

完成时间：2026-07-08

本次完成范围：
- 新增纯 core builder：`api/core/workflow/prd_compiler/package_builder.py`。
- 输入为 published workflow 的 graph JSON 加业务元数据，输出请求生命周期内的内存 ZIP，不落库、不写对象存储。
- 严格生成以下顶层结构：
  - `package.yaml`
  - `workflow.yaml`
  - `skills/`
  - `schemas/`
  - `data/`
- `package.yaml` 字段：
  - `id`
  - `version`
  - `title`
  - `scenario`
  - `entry_workflow`
- `workflow.yaml` 字段：
  - `id`
  - `entry_phase`
  - `phases`
  - phase 中包含 `id`、`title`、`skill`、`goal`，有上游依赖时包含 `context.load_phase_outputs`。
- `skills/<skill-id>/skill.md` 包含 front matter：
  - `name`
  - `description`
  - `model`
  - `tools`
  - `output_schema`
  - `context_policy`
- `schemas/<phase-id>.schema.json` 生成最小 JSON Schema。
- `data/` 当前仅生成空目录，不写入 PRD 原文或样例数据。
- builder 会拒绝导出疑似 secret 内容，并禁止 `graph.json`、`workflow.dsl.yaml`、`manifest.lock`、`dify/`、`compile/` 等内部产物路径。

涉及文件：
- `api/core/workflow/prd_compiler/package_builder.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_package_builder.py`

关键实现决策：
- package 从 Dify published workflow graph 反推业务 phase，不包含 Dify graph/DSL/IR。
- skill.md 不复制 Dify `prompt_template`，只使用节点标题和描述生成 package 指令，避免把完整 LLM prompt 打进 artifact。
- Start 节点只作为 Dify 输入入口，不作为 package phase；package 的 `entry_phase` 使用第一个非 Start 节点。

已验证：
```powershell
py -3.13 -m py_compile api\core\workflow\prd_compiler\package_builder.py api\tests\unit_tests\core\workflow\prd_compiler\test_package_builder.py
```

结果：通过。

新增测试覆盖：
- zip 顶层结构严格等于允许列表。
- `package.yaml`、`workflow.yaml`、`skill.md`、schema 文件存在且可解析。
- package 不包含 `prompt_template`、完整 prompt、`graph.json`、`workflow.dsl.yaml`。
- 疑似 secret 内容会被拒绝。

未验证项：
- 由于本机没有符合项目要求的 Python 3.12 + dev dependencies，尚未运行 pytest。
- package 字段是按当前参考包结构对齐的 MVP，复杂 branch、Human Input、Tool 等二阶段节点尚未映射。

### 阶段 2.2 交接：Package Export API

完成时间：2026-07-08

本次完成范围：
- 新增 service：`api/services/workflow_package_service.py`。
- 新增导出接口：

```http
POST /console/api/apps/{app_id}/workflows/{workflow_id}/package/export
```

- controller 读取 published workflow，调用 package service，直接返回 `application/zip`。
- 响应头包含：
  - `Content-Disposition: attachment; filename*=UTF-8''<package-id>-<version>.zip`
  - `Cache-Control: no-store`
- 只允许导出当前 app 下的 published workflow：
  - 通过 `get_app_model(...)` 绑定 app。
  - 通过 `WorkflowService.get_published_workflow_by_id(...)` 做 tenant/app scope 查询。
  - draft workflow 会被 `IsDraftWorkflowError` 拒绝。
- 导出失败不会修改 published workflow，也不会写 draft。

涉及文件：
- `api/controllers/console/app/workflow.py`
- `api/services/workflow_package_service.py`

关键实现决策：
- package 不在 publish 时同步生成，而是在下载请求中懒生成，符合“不长期保存”的产品决策。
- API 使用 `POST`，避免浏览器或代理对下载 URL 做非预期缓存。
- RBAC 使用 `APP_RELEASE_AND_VERSION`，与发布版本相关操作保持一致。

已验证：
```powershell
py -3.13 -m py_compile api\services\workflow_package_service.py api\controllers\console\app\workflow.py
```

结果：通过。

未验证项：
- 尚未在真实 Flask API 中请求该接口下载 zip。
- 尚未补 controller/service 层 pytest。

### 阶段 2.3 交接：前端 Package 下载入口

完成时间：2026-07-08

本次完成范围：
- 新增前端下载组件：`web/app/components/workflow/package-export/`。
- 新增下载调用：`exportWorkflowPackage(appID, workflowID)`。
- 组件挂载到 workflow header middle，位置在 PRD 生成入口之后、发布按钮区域之前。
- 使用 `useAppWorkflow(appID)` 读取当前 published workflow；只有存在 published 状态时显示入口。
- 点击下载后调用 package export API，读取 Blob，并通过 `downloadBlob(...)` 触发浏览器下载。
- 成功和失败提示均走 `workflow` i18n 命名空间。
- 已为所有 `web/i18n/*/workflow.json` 补充 `prdWorkflowPackage.*` 文案键。

涉及文件：
- `web/app/components/workflow/package-export/index.tsx`
- `web/app/components/workflow/package-export/README.md`
- `web/app/components/workflow-app/components/workflow-header/index.tsx`
- `web/service/use-workflow.ts`
- `web/i18n/*/workflow.json`

关键实现决策：
- 前端不自己猜 published workflow id，而是复用 `useAppWorkflow(appID)`；发布成功后已有 `useInvalidateAppWorkflow()` 会刷新该查询。
- 文件名优先从后端 `Content-Disposition` 解析，缺省回退为 `<workflowID>.zip`。
- 未发布时不展示入口；published workflow 尚未加载完成时按钮置灰。

已验证：
```powershell
node -e "const fs=require('fs'); const path=require('path'); for (const locale of fs.readdirSync('web/i18n')) { const file=path.join('web/i18n', locale, 'workflow.json'); if (fs.existsSync(file)) JSON.parse(fs.readFileSync(file,'utf8')); }"
```

结果：通过，所有 `workflow.json` 可解析。

未验证项：
- `pnpm --dir web type-check` 尚未完成；本地缺少 `web/node_modules`。
- 尚未在浏览器中验证“发布 workflow -> Package 按钮出现 -> 下载 zip -> 解压检查顶层结构”。

### 阶段 2.4 交接：第二阶段节点映射扩展

完成时间：2026-07-08

本次完成范围：
- Workflow IR 新增并启用二阶段 `phase.kind`：
  - `knowledge_retrieval`
  - `http_call`
  - `code_transform`
  - `tool_call`
  - `human_input`
  - `trigger`
- IR validator 从“二阶段节点不支持”改为“支持但必须满足最小配置合同”：
  - `knowledge_retrieval` 必须提供 `config.dataset_ids`。
  - `http_call` 必须提供 `config.url`。
  - `code_transform` 必须提供 `config.code`。
  - `tool_call` 必须提供 `config.provider_id`、`config.provider_type`、`config.tool_name`。
  - `trigger` 必须提供合法 `config.trigger_type`；webhook 需要 `webhook_url`；schedule 需要 cron 或 visual 配置；plugin 需要 `subscription_id`、`provider_id`、`provider_type`、`event_name`。
- Dify graph compiler 新增映射：
  - `knowledge_retrieval` -> `knowledge-retrieval`
  - `http_call` -> `http-request`
  - `code_transform` -> `code`
  - `tool_call` -> `tool`
  - `human_input` -> `human-input`
  - `trigger` -> `trigger-webhook` / `trigger-schedule` / `trigger-plugin`
- Human Input 默认使用 WebApp delivery，并在 PRD 未明确时补 `approve` / `reject` actions。
- Webhook Trigger 默认暴露 `_webhook_raw`，并把 IR 输入和 trigger phase outputs 编译为可被下游引用的 variables。
- Plugin Trigger 支持从 `phase.outputs` 生成最小 `output_schema`，并写入 `subscription_id`、`plugin_unique_identifier`、`event_node_version` 等运行所需字段。
- selector resolver 支持 `sys.*`、`env.*`、`conversation.*` 系统 selector，避免 schedule 类 trigger 被错误 fallback 到不存在的普通输出。
- Graph validator 扩展二阶段节点 payload 校验和输出变量收集：
  - Knowledge 输出 `result`
  - HTTP 输出 `body`、`status_code`、`headers`、`files`
  - Code 输出 `data.outputs`
  - Tool 输出 `text`、`files`、`json`
  - Human Input 输出 `__action_id`、`__action_value`、`__rendered_content` 和表单字段
  - Webhook Trigger 输出 `variables`
  - Plugin Trigger 输出 `output_schema.properties`
- Package builder 扩展二阶段节点 schema：
  - `code`
  - `knowledge-retrieval`
  - `http-request`
  - `tool`
  - `human-input`
- Package builder 继续排除 `start` 和全部 trigger 节点，保证下载 package 不包含运行入口或 Dify 内部 graph/DSL。
- `prd_to_workflow_ir.md` planner prompt 已更新为二阶段节点支持口径，并明确“缺配置写入 warnings/missing_requirements，不伪造实现”。

涉及文件：
- `api/core/workflow/prd_compiler/entities.py`
- `api/core/workflow/prd_compiler/validator.py`
- `api/core/workflow/prd_compiler/dify_compiler.py`
- `api/core/workflow/prd_compiler/package_builder.py`
- `api/core/workflow/prd_compiler/prompts/prd_to_workflow_ir.md`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_ir_validator.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_dify_compiler.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_package_builder.py`

关键实现决策：
- 二阶段节点不是让 LLM 自由编造，而是走“配置齐全才生成”的保守策略；缺少知识库、工具、触发器订阅、URL 或代码时，IR validator 会阻止进入 graph compile / draft sync。
- Trigger 与 Start 一样被视为 start-like node，graph 中必须且只能存在一个 `start` 或 trigger。
- Trigger 不进入 package phase；package 是用户自定义可下载 artifact，不是 Dify runtime 入口声明。
- Tool、Knowledge、Plugin Trigger 仍依赖 Dify 中真实存在且有权限的资源；静态编译只校验字段形态，不能替代真实资源权限校验。
- Human Input 第一版只生成最小 WebApp 审批流；Email/Slack/Teams/Discord delivery 留给后续在真实企业配置中补齐。

新增测试覆盖：
- IR validator：
  - `http_call` 缺少 `url` 时返回 `missing_phase_config`。
  - `human_input` 作为二阶段节点可通过 IR 校验。
  - plugin trigger 缺少 `subscription_id/provider_id/provider_type/event_name` 时失败。
- Dify compiler / graph validator：
  - Start -> Human Input -> End。
  - Start -> HTTP Request -> Code -> End。
  - Start -> Knowledge Retrieval -> Tool -> End。
  - Webhook Trigger -> LLM -> End。
  - Schedule Trigger -> LLM -> End，并验证 `sys.time` selector。
  - Plugin Trigger -> LLM -> End。
- Package builder：
  - 二阶段 HTTP/Code/Human Input schema 可导出。
  - Trigger 节点不会进入 package phase。

已验证：
```powershell
py -3.13 -m py_compile api\core\workflow\prd_compiler\entities.py api\core\workflow\prd_compiler\validator.py api\core\workflow\prd_compiler\dify_compiler.py api\core\workflow\prd_compiler\package_builder.py api\tests\unit_tests\core\workflow\prd_compiler\test_ir_validator.py api\tests\unit_tests\core\workflow\prd_compiler\test_dify_compiler.py api\tests\unit_tests\core\workflow\prd_compiler\test_package_builder.py
```

结果：通过。

尝试但未完成：
```powershell
uv run --project api pytest api/tests/unit_tests/core/workflow/prd_compiler/test_ir_validator.py api/tests/unit_tests/core/workflow/prd_compiler/test_dify_compiler.py api/tests/unit_tests/core/workflow/prd_compiler/test_package_builder.py
```

结果：本机 PATH 中没有 `uv`，报 `The term 'uv' is not recognized as the name of a cmdlet, function, script file, or operable program.`。

```powershell
py -3.13 -m pytest api/tests/unit_tests/core/workflow/prd_compiler/test_ir_validator.py api/tests/unit_tests/core/workflow/prd_compiler/test_dify_compiler.py api/tests/unit_tests/core/workflow/prd_compiler/test_package_builder.py
```

结果：Python 3.13 解释器缺少 pytest，报 `No module named pytest`。

未验证项：
- 尚未用真实 Dify draft sync 验证二阶段节点 graph 是否全部被当前版本画布和后端运行时接受。
- 尚未对 Knowledge Retrieval、Tool、Plugin Trigger 做真实资源权限和订阅校验。
- 尚未执行真实 workflow debug/run 验证 Human Input、HTTP、Code、Trigger 的运行态行为。
- 尚未跑完整 pytest、ruff、mypy/type-check。

## 7. 阶段 3：右侧自然语言编辑器

当前状态：后端 graph patch、前端右侧助手面板已完成静态实现；尚未完成真实浏览器端到端验收。

### 阶段目标

在 workflow 编辑页右侧提供自然语言助手，用户可以输入修改意图，系统返回 graph patch 预览，用户确认后应用到 draft。

### 建议新增或修改文件

后端：

- `api/services/workflow_graph_edit_service.py`
- `api/core/workflow/prd_compiler/graph_patch.py`
- `api/core/workflow/prd_compiler/prompts/graph_patch.md`

前端：

- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/panel/`
- `web/app/components/workflow/nl-edit-assistant/`
- `web/i18n/en-US/`

### 关键决策

- 使用独立 graph patch prompt，不复用从零生成 workflow 的 prompt。
- 默认 `dry_run=true`，先返回预览。
- 未经用户确认不得修改 draft。
- patch 应类型化，至少包括 `add_node`、`update_node`、`remove_node`、`add_edge`、`remove_edge`。
- patch 应用后必须走同一套 graph validator。

### 实现交接模板

阶段完成后补充：

- NL edit API 路径、请求体和响应体。
- patch schema。
- patch apply 规则。
- preview graph 刷新方式。
- 用户确认后 apply 的链路。
- 无效 patch 的错误形态。
- 前端面板入口位置。
- 新增测试和验收命令。

### 阶段验收

- 用户能用自然语言修改已有节点配置。
- 用户能预览 proposed changes。
- 用户拒绝时 draft 不变化。
- 用户确认后变更写入 draft 并刷新画布。
- 无效 patch 不会写入 draft。

### 阶段 3.1 交接：后端 Graph Patch 能力

完成时间：2026-07-08

本次完成范围：
- 新增自然语言编辑后端服务 `WorkflowGraphEditService`，负责读取 tenant/app 范围内 draft workflow、规划或接收 typed patch、内存生成 preview graph、校验 graph，并在非 dry-run 时写回 draft。
- 新增纯核心模块 `core.workflow.prd_compiler.graph_patch`，包含：
  - `WorkflowGraphEditPayload`
  - `WorkflowGraphEditResponse`
  - `WorkflowGraphPatch`
  - `GraphPatchOperation`
  - `WorkflowGraphPatchPlanner`
  - `apply_graph_patch(...)`
- 新增独立 prompt：`api/core/workflow/prd_compiler/prompts/graph_patch.md`，明确只返回 JSON patch，不复用从零生成 workflow 的 prompt。
- 新增接口：
```http
POST /console/api/apps/{app_id}/workflows/draft/nl-edit
```
- 请求体支持：
  - `instruction`
  - `selected_node_id`
  - `scope`
  - `dry_run`
  - `draft_hash`
  - `model_config`
  - 可选 `patch`
- patch 操作白名单：
  - `add_node`
  - `update_node`
  - `remove_node`
  - `add_edge`
  - `remove_edge`
- `dry_run=true` 只返回 preview，不写 draft。
- `dry_run=false` 时优先复用前端确认过的 `patch`，再次 apply + validate 后调用 `WorkflowService.sync_draft_workflow(...)` 写入 draft。
- draft hash 不匹配时继续抛出 `WorkflowHashNotEqualError`，controller 转成既有 `DraftWorkflowNotSync`。
- 无效 patch、graph validator 失败、draft sync 失败都会返回 `draft_synced=false`，不产生半写入状态。

涉及文件：
- `api/core/workflow/prd_compiler/graph_patch.py`
- `api/core/workflow/prd_compiler/prompts/graph_patch.md`
- `api/services/workflow_graph_edit_service.py`
- `api/controllers/console/app/workflow.py`
- `api/tests/unit_tests/core/workflow/prd_compiler/test_graph_patch.py`

关键实现决策：
- graph patch apply 保持纯函数式：对 graph 深拷贝后修改，避免 preview 阶段污染原 draft graph。
- LLM planner 只把精简后的 graph 摘要传入 prompt，避免把完整 prompt、secret 或不必要内部状态暴露给模型。
- apply 前后统一走 `validate_dify_graph(...)`，不让 LLM patch 绕过既有 graph 安全边界。
- `remove_node` 会同步移除关联边；是否导致缺少 terminal 等结构问题交给 graph validator 判定。
- 后端响应返回 graph summary 和 preview graph，但前端当前只展示 summary/operation 数量；正式刷新仍以 draft refetch 为准。

新增测试覆盖：
- `update_node` 修改节点 data，且不污染原 graph。
- `remove_node` 会删除关联边，且缺少 Answer/End 时 validator 失败。
- `add_node` + `add_edge` 能生成可通过 validator 的最小路径。

已验证：
```powershell
py -3.13 -m py_compile api\core\workflow\prd_compiler\graph_patch.py api\services\workflow_graph_edit_service.py api\controllers\console\app\workflow.py api\tests\unit_tests\core\workflow\prd_compiler\test_graph_patch.py
```

结果：通过。

未验证项：
- 尚未运行 pytest；本机缺少符合项目要求的 Python 3.12 + dev dependencies 环境。
- 尚未在真实 Dify app 中请求 `/workflows/draft/nl-edit` 验证 LLM patch 规划、dry-run preview、apply 写回 draft 的端到端效果。

### 阶段 3.2 交接：前端右侧自然语言助手面板

完成时间：2026-07-08

本次完成范围：
- 新增 `web/app/components/workflow/nl-edit-assistant/` 功能模块和 README。
- 在 workflow header 中新增 `AI Edit` 入口按钮，受 `accessControl.canEdit` 控制。
- 在 workflow store 的 panel slice 中新增：
  - `showNlEditAssistantPanel`
  - `setShowNlEditAssistantPanel`
- 在 `workflow-panel.tsx` 的右侧 panel 区域动态挂载 `WorkflowNlEditAssistant`。
- 助手面板支持：
  - 读取当前选中节点 `node.data.selected`。
  - 输入自然语言修改指令。
  - 复用 workflow generator 的模型配置存储和模型参数弹窗。
  - 先调用后端 `dry_run=true` 获取预览。
  - 展示 patch summary、operation 数量和最多 3 条 warning。
  - 用户确认后带上 preview 返回的 `patch` 调用 `dry_run=false`。
  - apply 成功后关闭面板并调用 `handleRefreshWorkflowDraft()` 刷新画布。
- 新增前端 API 类型和调用函数：
  - `WorkflowGraphPatchOperation`
  - `WorkflowGraphPatch`
  - `WorkflowGraphEditBody`
  - `WorkflowGraphEditResponse`
  - `editWorkflowGraphWithNl(...)`
- 已为全部 `web/i18n/*/workflow.json` 补充 `workflowGraphEdit.*` 文案 key。

涉及文件：
- `web/app/components/workflow/nl-edit-assistant/index.tsx`
- `web/app/components/workflow/nl-edit-assistant/trigger.tsx`
- `web/app/components/workflow/nl-edit-assistant/README.md`
- `web/app/components/workflow-app/components/workflow-header/index.tsx`
- `web/app/components/workflow-app/components/workflow-panel.tsx`
- `web/app/components/workflow/store/workflow/panel-slice.ts`
- `web/service/use-workflow.ts`
- `web/i18n/*/workflow.json`

关键实现决策：
- 前端不直接消费 preview graph 来替换画布，避免和 Dify 现有 draft 状态产生双源；真正应用成功后统一 refetch draft。
- apply 阶段复用 preview 返回的 typed `patch`，避免用户确认后模型重新生成不同 patch。
- 右侧助手作为 `Panel` 的 right component 动态加载，与 debug/preview、变量面板、评论面板共用现有右侧 panel 布局。
- 未选中节点时 `scope=workflow`；选中节点时 `scope=selected_node` 并传 `selected_node_id`。

已验证：
```powershell
node -e "const fs=require('fs'); const path=require('path'); const missing=[]; for (const locale of fs.readdirSync('web/i18n')) { const file=path.join('web/i18n', locale, 'workflow.json'); if (!fs.existsSync(file)) continue; const data=JSON.parse(fs.readFileSync(file,'utf8')); for (const key of ['workflowGraphEdit.trigger','workflowGraphEdit.title','workflowGraphEdit.selectedNode','workflowGraphEdit.noSelectedNode','workflowGraphEdit.instruction','workflowGraphEdit.placeholder','workflowGraphEdit.preview','workflowGraphEdit.previewReady','workflowGraphEdit.previewFailed','workflowGraphEdit.apply','workflowGraphEdit.applied','workflowGraphEdit.applyFailed','workflowGraphEdit.noSummary','workflowGraphEdit.operations']) if (!(key in data)) missing.push(locale+':'+key); } if (missing.length) { console.error(missing.join('\n')); process.exit(1); } console.log('workflow i18n ok');"
```

结果：通过，全部 workflow locale JSON 可解析且包含 `workflowGraphEdit.*` key。

另做 UTF-8 内容抽查：
```powershell
node -e "const fs=require('fs'); const v=JSON.parse(fs.readFileSync('web/i18n/zh-Hans/workflow.json','utf8'))['workflowGraphEdit.title']; console.log([...v].map(c=>c.codePointAt(0).toString(16)).join(' '));"
```

结果：输出 `7528 20 41 49 20 4fee 6539 5de5 4f5c 6d41`，对应“用 AI 修改工作流”，确认文件内容本身不是乱码。

前端未完成验证：
```powershell
pnpm --dir web type-check
pnpm --dir web lint --file app/components/workflow/nl-edit-assistant/index.tsx --file app/components/workflow/nl-edit-assistant/trigger.tsx --file app/components/workflow-app/components/workflow-panel.tsx --file app/components/workflow-app/components/workflow-header/index.tsx --file service/use-workflow.ts
```

结果：未进入实际 type-check/lint。`pnpm` 先尝试安装 workspace 依赖，网络出现多次 `ECONNRESET`、`timeout`，并因并发安装出现一次：
```text
[ERR_PNPM_EPERM] [importPackage ... path-key_tmp_8436_4 -> ... path-key] EPERM: operation not permitted, rename ...
```

需要在依赖安装稳定后重跑以上两条命令。

未验证项：
- 尚未在浏览器中验证点击 header `AI Edit` 后面板出现。
- 尚未验证选中节点上下文传入后端。
- 尚未验证 preview、取消、apply 成功刷新 draft 的完整 UI 链路。
- 尚未验证真实模型返回的 patch 是否能稳定通过 graph validator。

## 8. 阶段 4：编译器抽离准备

当前状态：未启动；但阶段 1 起编码时就要保留边界。

### 阶段目标

Dify 内闭环稳定后，将 PRD compiler 从 Dify 业务代码中逐步解耦，Dify 成为目标平台 adapter 之一。

### 编码边界

- `prd_compiler` 不直接依赖 Flask controller。
- IR、validator、package builder 尽量保持纯函数或低副作用。
- Dify graph 生成放在 Dify adapter 层。
- Wiki context 获取通过 service/provider 接口封装。
- LLM 调用通过 service/provider 接口封装。

### 未来目标结构

```text
prd-compiler-service/
  core/
    ir/
    planner/
    validators/
    package_builder/
  adapters/
    dify/
    coze/
  providers/
    wiki_context/
    llm/
```

### 实现交接模板

阶段完成后补充：

- 已抽离模块列表。
- Dify adapter 的接口边界。
- provider 接口边界。
- 独立测试命令。
- 与 Dify 仓库仍耦合的点。
- 是否具备新增 Coze adapter 的条件。

### 阶段验收

- PRD compiler 的单元测试不需要启动 Flask。
- Dify adapter 可以单独测试 IR -> Dify graph。
- package builder 可以单独测试 IR/package model -> zip。
- 后续新增目标平台 adapter 不需要改 Dify controller 主链路。

## 9. 继续开发前的优先清单

1. 完成阶段 0 未验证项：用真实环境验证 fixture 的结构校验和 draft sync。
2. 启动阶段 1 后端骨架：DTO、controller、service、IR model、validator。
3. 先使用 mock Wiki 和 mock LLM 跑通 IR -> graph -> draft sync。
4. 再接入真实 Wiki Tree Context API。
5. 最后接入真实 Qwen/GPT，并调 prompt。
6. 阶段 1 通过后再进入 package builder，不要提前扩第二阶段节点。
