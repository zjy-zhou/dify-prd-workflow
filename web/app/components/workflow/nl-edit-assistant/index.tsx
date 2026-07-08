'use client'

import type { FormValue } from '@/app/components/header/account-setting/model-provider-page/declarations'
import type { CompletionParams, ModelModeType } from '@/types/app'
import { Button } from '@langgenius/dify-ui/button'
import { cn } from '@langgenius/dify-ui/cn'
import { Textarea } from '@langgenius/dify-ui/textarea'
import { toast } from '@langgenius/dify-ui/toast'
import { RiCloseLine } from '@remixicon/react'
import { useMutation } from '@tanstack/react-query'
import { memo, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useStore as useReactflow } from 'reactflow'
import { useShallow } from 'zustand/react/shallow'
import { ModelTypeEnum } from '@/app/components/header/account-setting/model-provider-page/declarations'
import {
  useModelListAndDefaultModelAndCurrentProviderAndModel,
} from '@/app/components/header/account-setting/model-provider-page/hooks'
import ModelParameterModal from '@/app/components/header/account-setting/model-provider-page/model-parameter-modal'
import { useHooksStore } from '@/app/components/workflow/hooks-store'
import { useStore } from '@/app/components/workflow/store'
import { editWorkflowGraphWithNl, type WorkflowGraphEditResponse } from '@/service/use-workflow'
import { EMPTY_WORKFLOW_GENERATOR_MODEL, useWorkflowGeneratorModel } from '../workflow-generator/storage'

async function resolveErrorMessage(error: unknown): Promise<string> {
  if (error instanceof Response) {
    try {
      const data = await error.json() as { message?: string, description?: string }
      return data.message || data.description || ''
    }
    catch {
      return ''
    }
  }
  if (error instanceof Error)
    return error.message
  return String(error || '')
}

const panelClassName = [
  'relative flex h-full w-[380px] flex-col rounded-l-2xl',
  'border border-components-panel-border bg-components-panel-bg-alt shadow-xl',
].join(' ')

function WorkflowNlEditAssistant() {
  const { t } = useTranslation('workflow')
  const appID = useStore(s => s.appId)
  const draftHash = useStore(s => s.syncWorkflowDraftHash)
  const setShowNlEditAssistantPanel = useStore(s => s.setShowNlEditAssistantPanel)
  const handleRefreshWorkflowDraft = useHooksStore(s => s.handleRefreshWorkflowDraft)
  const [instruction, setInstruction] = useState('')
  const [preview, setPreview] = useState<WorkflowGraphEditResponse | null>(null)
  const [model, setModel] = useWorkflowGeneratorModel()
  const selectedNode = useReactflow(useShallow((s) => {
    const node = s.getNodes().find(candidate => candidate.data?.selected)
    if (!node)
      return null
    return {
      id: node.id,
      title: String(node.data?.title || node.id),
    }
  }))
  const { defaultModel } = useModelListAndDefaultModelAndCurrentProviderAndModel(ModelTypeEnum.textGeneration)

  useEffect(() => {
    if (defaultModel && !model.name) {
      setModel(prev => ({
        ...(prev ?? EMPTY_WORKFLOW_GENERATOR_MODEL),
        name: defaultModel.model,
        provider: defaultModel.provider.provider,
      }))
    }
  }, [defaultModel, model.name, setModel])

  const handleModelChange = useCallback((newValue: {
    modelId: string
    provider: string
    mode?: string
  }) => {
    setModel(prev => ({
      ...(prev ?? EMPTY_WORKFLOW_GENERATOR_MODEL),
      provider: newValue.provider,
      name: newValue.modelId,
      mode: newValue.mode as ModelModeType,
    }))
  }, [setModel])

  const handleCompletionParamsChange = useCallback((newParams: FormValue) => {
    setModel(prev => ({
      ...(prev ?? EMPTY_WORKFLOW_GENERATOR_MODEL),
      completion_params: newParams as CompletionParams,
    }))
  }, [setModel])

  const buildBody = useCallback((dryRun: boolean) => {
    return {
      instruction: instruction.trim(),
      selected_node_id: selectedNode?.id,
      scope: selectedNode ? 'selected_node' as const : 'workflow' as const,
      dry_run: dryRun,
      ...(draftHash ? { draft_hash: draftHash } : {}),
      model_config: {
        provider: model.provider,
        name: model.name,
        mode: model.mode || EMPTY_WORKFLOW_GENERATOR_MODEL.mode,
        completion_params: model.completion_params,
      },
      ...(dryRun ? {} : { patch: preview?.patch || null }),
    }
  }, [draftHash, instruction, model, preview?.patch, selectedNode])

  const previewMutation = useMutation({
    mutationFn: () => editWorkflowGraphWithNl(appID, buildBody(true)),
    onSuccess: (response) => {
      setPreview(response)
      if (response.result !== 'success') {
        const message = response.warnings?.[0] || response.missing_requirements?.[0]
        toast.error(message || t('workflowGraphEdit.previewFailed'))
        return
      }
      toast.success(t('workflowGraphEdit.previewReady'))
    },
    onError: async (error) => {
      const message = await resolveErrorMessage(error)
      toast.error(message || t('workflowGraphEdit.previewFailed'))
    },
  })

  const applyMutation = useMutation({
    mutationFn: () => editWorkflowGraphWithNl(appID, buildBody(false)),
    onSuccess: (response) => {
      if (response.result !== 'success' || !response.draft_synced) {
        const message = response.warnings?.[0] || response.missing_requirements?.[0]
        toast.error(message || t('workflowGraphEdit.applyFailed'))
        return
      }
      toast.success(t('workflowGraphEdit.applied'))
      setShowNlEditAssistantPanel(false)
      handleRefreshWorkflowDraft()
    },
    onError: async (error) => {
      const message = await resolveErrorMessage(error)
      toast.error(message || t('workflowGraphEdit.applyFailed'))
    },
  })

  const canPreview = !!instruction.trim() && !!model.name && !!model.provider
  const canApply = !!preview?.patch && preview.result === 'success'

  return (
    <div className={panelClassName}>
      <div className="flex shrink-0 items-center justify-between p-4 pb-0">
        <div className="system-xl-semibold text-text-primary">
          {t('workflowGraphEdit.title')}
        </div>
        <button
          type="button"
          className="flex size-6 items-center justify-center"
          aria-label={t('operation.close', { ns: 'common' })}
          onClick={() => setShowNlEditAssistantPanel(false)}
        >
          <RiCloseLine className="size-4 text-text-tertiary" aria-hidden="true" />
        </button>
      </div>
      <div className="shrink-0 px-4 py-2 system-sm-regular text-text-tertiary">
        {selectedNode
          ? t('workflowGraphEdit.selectedNode', { title: selectedNode.title })
          : t('workflowGraphEdit.noSelectedNode')}
      </div>
      <div className="shrink-0 px-4 pb-3">
        <ModelParameterModal
          popupClassName="w-[340px]!"
          isAdvancedMode={true}
          provider={model.provider}
          completionParams={model.completion_params}
          modelId={model.name}
          setModel={handleModelChange}
          onCompletionParamsChange={handleCompletionParamsChange}
          hideDebugWithMultipleModel
        />
      </div>
      <div className="flex min-h-0 grow flex-col gap-3 overflow-y-auto px-4 pb-3">
        <label className="block">
          <div className="mb-1.5 system-sm-medium text-text-secondary">
            {t('workflowGraphEdit.instruction')}
          </div>
          <Textarea
            className="min-h-[128px] resize-none"
            value={instruction}
            disabled={previewMutation.isPending || applyMutation.isPending}
            placeholder={t('workflowGraphEdit.placeholder')}
            onChange={e => setInstruction(e.target.value)}
          />
        </label>
        {preview && (
          <div className="rounded-lg bg-background-section-burn p-3">
            <div className="system-sm-medium text-text-secondary">{t('workflowGraphEdit.preview')}</div>
            <div className="mt-1 system-xs-regular text-text-tertiary">
              {preview.summary || t('workflowGraphEdit.noSummary')}
            </div>
            <div className="mt-2 system-xs-regular text-text-tertiary">
              {t('workflowGraphEdit.operations', { count: preview.patch?.operations?.length || 0 })}
            </div>
            {!!preview.warnings?.length && (
              <div className="mt-2 space-y-1">
                {preview.warnings.slice(0, 3).map((warning, index) => (
                  <div key={`${warning}-${index}`} className="system-xs-regular text-text-warning">
                    {warning}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="flex shrink-0 justify-end gap-2 border-t border-divider-subtle p-4">
        <Button
          disabled={previewMutation.isPending || applyMutation.isPending}
          onClick={() => setShowNlEditAssistantPanel(false)}
        >
          {t('operation.cancel', { ns: 'common' })}
        </Button>
        <Button
          className={cn(!canPreview && 'opacity-50')}
          disabled={!canPreview || previewMutation.isPending || applyMutation.isPending}
          loading={previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          {t('workflowGraphEdit.preview')}
        </Button>
        <Button
          variant="primary"
          disabled={!canApply || previewMutation.isPending || applyMutation.isPending}
          loading={applyMutation.isPending}
          onClick={() => applyMutation.mutate()}
        >
          {t('workflowGraphEdit.apply')}
        </Button>
      </div>
    </div>
  )
}

export default memo(WorkflowNlEditAssistant)
