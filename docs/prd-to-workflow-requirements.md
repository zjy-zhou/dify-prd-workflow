# PRD 到工作流生成需求文档

状态：草稿
负责人：待定
目标仓库：Dify 开源版二次开发
最后更新：2026-07-07

## 摘要

在 Dify 内建设一条 PRD 到节点式工作流的生成链路。用户输入带有清晰步骤、输入输出规范的 PRD 文档后，系统通过现有 Wiki Tree Context API 获取结构化 PRD 上下文，再由 LLM 理解和编译，生成 Dify 兼容的 workflow graph，并自动渲染到 Dify 现有无限画布中。用户可以继续使用 Dify 原生节点配置、调试、保存草稿、发布和正式 API 调用能力。

第一阶段以 Dify 为主目标平台。Coze 风格输出只作为未来 adapter 方向预留，不纳入 MVP 的运行闭环。

## 问题背景

用户可以在 PRD、Wiki 或业务文档中描述一套可执行流程，但把这些文档手工转换成节点式 Skill/Workflow 很慢，也容易遗漏输入输出、条件分支、校验规则和依赖关系。

Dify 已经具备成熟的画布、节点、变量、调试、草稿、发布、正式 API、模型配置、知识库和插件能力。当前缺的是一层“PRD 编译器”：把结构化 PRD 意图转换成可运行的 Dify workflow draft。

## 目标用户

- 写 PRD 的产品、解决方案或业务设计人员。
- 需要快速搭建 Dify 工作流草稿的工作流构建者。
- 需要沉淀、复用、审计工作流 package 的企业团队。
- 希望通过自然语言继续修改节点和流程的运营或实施人员。

## 产品目标

- 将 PRD 上下文转换成有效的 Dify 工作流草稿。
- 复用 Dify 现有画布、节点、调试、草稿保存、发布和正式 API 能力。
- 在发布可运行快照后生成自定义 package 下载文件，便于审计、迁移和复用；MVP 不长期保存 package artifact。
- 在工作流编辑页右侧提供自然语言对话框，用于修改节点或工作流结构。
- 让 PRD 编译能力保持相对独立，后续可抽出为独立服务，并支持更多目标平台。

## 非目标

- 不重做 Dify 的画布、节点系统、运行时、调试、发布和 API 服务。
- MVP 不完整实现 Coze 导出或 Coze 运行。
- 不允许生成结果绕过人工确认直接发布。
- 不承诺对模糊 PRD 生成完全正确的工作流。
- 不在 package 中保存真实密钥、模型凭证或外部 API Key。

## 输入来源

### PRD 上下文接口

PRD 到结构化上下文这一步调用现有 Wiki Tree Context API，接口文档路径：

```text
E:/2-项目资料/0-元策略编译器项目/4-接口数据及文档/wiki_tree_context_api.md
```

接口形态：

- 请求方法：`POST`
- 接口路径：`/api/wiki/tree/context`
- Headers：
  - `Content-Type: application/json`
  - `LIGHTRAG-WORKSPACE: <workspace_id>`
- Body：
  - `doc_id`
  - `tree_type`，MVP 默认 `reasoning_action`
  - `force_rebuild`，默认 `false`

关键响应字段：

- `tree_json`：递归结构化知识树。
- `outline_md`：大纲 Markdown。
- `dimension_bundle.markdown`：可选，维度表 Markdown。
- `raw_bundle.markdown`：可选，原始 Markdown。
- `source_name`、`version`、`tree_type`：用于溯源和 package 生成。

`tree_json` 节点类型包括：

```text
root
section
action
note
rule
condition
outcome
```

这些节点应作为 workflow phase、节点、条件、输出和规则抽取的主要来源。

### Package 参考格式

发布后的自定义 package 参考目录：

```text
E:/2-项目资料/0-元策略编译器项目/1-prd_package/wig-opportunity-discovery/
```

已观察到的结构：

```text
package.yaml
workflow.yaml
skills/
schemas/
data/
```

其中：

- `package.yaml` 保存 package 元信息，例如 id、version、title、scenario、entry_workflow。
- `workflow.yaml` 保存阶段编排，例如 phase id、title、skill、goal、context、confirmation。
- `skills/<skill-id>/skill.md` 保存每个阶段的 skill 元数据和执行指令。
- `schemas/*.schema.json` 保存阶段输入输出规范。
- `data/` 保存样例数据、证据、知识或业务数据。

## 核心用户流程

### 流程一：从 PRD 生成 Dify 工作流

1. 用户打开 Dify 工作流编辑页。
2. 用户打开新增的 PRD 上传/生成面板。
3. 用户选择 PRD 来源：
   - Wiki 文档 id 和 workspace id，MVP 优先支持。
   - 粘贴 PRD 文本，作为可选兜底。
   - 上传文件，后续版本支持。
4. 后端调用 Wiki Tree Context API 获取结构化 PRD 上下文。
5. 后端将 PRD 上下文编译为平台无关的中间表示。
6. 后端将中间表示编译为 Dify workflow graph。
7. 后端校验 graph。
8. 校验通过后，后端写入 Dify draft，或返回给前端再调用现有 draft sync。
9. 前端刷新 draft，Dify 画布自动渲染节点和连线。
10. 用户继续检查、编辑、调试并发布。

### 流程二：发布并生成 package 快照

1. 用户发布已生成或已编辑的工作流。
2. Dify 按原有逻辑生成 published workflow 快照。
3. 系统基于 published workflow、PRD 源信息、IR 和校验结果生成自定义 package。
4. 用户可以下载、查看或后续重新导入 package。

### 流程三：通过自然语言修改节点

1. 用户在工作流编辑页右侧打开自然语言助手。
2. 用户输入修改意图，例如“在 opportunity-scoring 后增加人工确认节点”。
3. 助手读取当前 workflow graph、选中节点和上下游上下文。
4. 后端返回一个 graph patch 或预览 graph。
5. 用户预览变更并确认应用。
6. 变更通过现有 draft sync 保存。

## 功能需求

### PRD 输入

- 支持 Wiki 来源输入：`doc_id`、`tree_type`、`LIGHTRAG-WORKSPACE`。
- 展示已获取的 PRD 标题、source_name 和 outline 摘要。
- 默认使用 `force_rebuild=false`。
- 外部接口失败时展示明确错误。
- 保存 source metadata，用于后续 package 溯源。

### PRD 编译

- 将 Wiki `tree_json`、`outline_md`、可选 raw Markdown 转为编译请求。
- 在获取结构化上下文后再调用 LLM。
- LLM 输出应先进入中间表示，而不是直接成为最终 Dify graph。
- 能识别缺失输入、模糊步骤、未支持节点意图。
- 对不确定内容返回 warnings 和 missing_requirements，不能静默猜测。

### Dify Graph 生成

MVP 必须生成有效 Dify graph，至少包含：

- Start 节点。
- LLM/任务节点。
- PRD 中存在条件时生成条件分支。
- Answer 或 End 节点。

后续迭代支持：

- Knowledge Retrieval 节点。
- HTTP Request 或 Tool 节点。
- Code 节点。
- Human Input 或审批节点。
- Trigger 节点。

生成的 graph 必须兼容 Dify 现有 draft sync 和画布渲染。

### 画布集成

- 复用 `web/app/components/workflow/`。
- 优先复用现有 `workflow-generator` 的 UI 和交互模式。
- 不新增第二套画布。
- 生成结果进入 Dify draft 后，应像普通工作流一样可编辑、可调试、可发布。

### 发布和 package 快照

- 发布仍使用 Dify 原有 `/apps/{app_id}/workflows/publish` 流程。
- 发布成功后可生成自定义 package 下载文件。
- MVP 不长期保存 package artifact，不落库、不写对象存储，只按需生成下载。
- 导出的 package 必须严格遵循参考目录格式，只包含：
  - `package.yaml`
  - `workflow.yaml`
  - `skills/`
  - `schemas/`
  - `data/`
- 不得在导出 package 中新增 `dify/`、`compile/`、`manifest.lock`、`README.md` 等额外顶层文件或目录，除非 package 标准后续显式升级。
- Dify graph、IR、validation、source metadata 只作为内部生成和校验过程数据，不写入用户下载的 package。
- Dify DSL 不是参考 package 的既有内容，不进入 MVP package。
- package 不得包含真实凭证或密钥。

### 自然语言编辑

- 右侧助手支持选中节点上下文和全局 workflow 上下文。
- 助手输出 proposed patch，而不是直接隐藏修改 graph。
- 用户可以预览、应用或拒绝修改。
- 应用后的变更必须走现有 draft sync。

## UX 要求

- PRD 生成入口位于工作流编辑页内，靠近现有 workflow generator 体验。
- 生成流程展示阶段状态：
  - 获取 PRD 上下文。
  - 编译 workflow plan。
  - 生成 graph。
  - 校验 graph。
  - 写入 draft。
- 覆盖当前 draft 前必须提示用户。
- 当前 draft 有未保存变更时，必须要求确认。
- 右侧自然语言助手不能永久遮挡现有节点配置面板。

## 成功指标

- 生成的 draft 可以在 Dify 画布正常打开。
- 生成的 graph 可以保存为 draft，且无后端校验错误。
- 支持节点可以完成一次基础 debug 运行。
- 用户可以发布生成后的 workflow。
- 发布后可以生成 package 快照。
- 在 MVP 测评集中，至少 80% 的结构化 PRD 能生成仅需少量人工修改的 workflow draft。

## 验收标准

- 给定合法 Wiki `doc_id`，用户可以生成 Dify workflow draft。
- 外部 API 失败时，用户得到明确错误，当前 draft 不被修改。
- graph 校验失败时，用户看到错误详情，无效 graph 不会写入 draft。
- 发布成功后，published workflow 仍可通过 Dify 现有运行时调用。
- 发布成功后，可下载严格符合参考格式的 package，包含 `package.yaml`、`workflow.yaml`、`skills/`、`schemas/`、`data/`。
- 自然语言编辑返回变更预览，用户确认后才应用。

## 风险和失败模式

- 外部 PRD API 返回的递归树过大，超出 LLM 上下文。
- PRD tree 虽结构化，但语义仍不明确。
- LLM 输出引用了不支持的 Dify 节点类型或无效变量路径。
- 生成 graph 意外覆盖用户当前 draft。
- package 导出未正确脱敏，导致密钥泄露。
- 自然语言编辑生成了无效的局部 graph patch。
- Dify 版本升级导致 graph shape 或节点必填字段变化。

## 已确认决策

- 生成结果由后端校验后直接写入 Dify draft，前端刷新 draft 并渲染画布。
- package artifact 只生成下载文件，不长期保存。
- 导出的 package 必须严格按照给定 package 格式生成，只包含 `package.yaml`、`workflow.yaml`、`skills/`、`schemas/`、`data/`。
- 参考 package 中没有 Dify DSL，MVP package 不包含 Dify DSL，也不包含 Dify graph、IR、validation 等内部编译产物。
- MVP 节点类型只支持 Start、LLM、IfElse、Answer/End。
- 第二阶段再支持 Knowledge Retrieval、HTTP Request、Code、Tool、Human Input、Trigger。
- 人工确认第一版先保留在 package 的 `confirmation` 字段和编译 IR 中；Dify graph 中暂不强制映射为正式审批节点，等第二阶段支持 Human Input 后再映射。
- 右侧自然语言助手使用独立 graph patch prompt，不复用从零生成 workflow 的 prompt。
- compile artifacts 默认不保存完整 PRD 原文和完整 LLM prompt，只保存 source metadata、IR、graph、validation 和必要摘要；如需保存更多内容，需受企业数据规则控制。
- MVP 仍优先只支持 Wiki PRD 来源。
