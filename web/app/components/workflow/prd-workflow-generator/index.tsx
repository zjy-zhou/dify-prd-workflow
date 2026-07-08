'use client'

import type { FormValue } from '@/app/components/header/account-setting/model-provider-page/declarations'
import type { CompletionParams, ModelModeType } from '@/types/app'
import {
  AlertDialog,
  AlertDialogActions,
  AlertDialogCancelButton,
  AlertDialogConfirmButton,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from '@langgenius/dify-ui/alert-dialog'
import { Button } from '@langgenius/dify-ui/button'
import { Checkbox } from '@langgenius/dify-ui/checkbox'
import { Dialog, DialogContent } from '@langgenius/dify-ui/dialog'
import { Input } from '@langgenius/dify-ui/input'
import { toast } from '@langgenius/dify-ui/toast'
import { RiCloseLine, RiFileTextLine } from '@remixicon/react'
import { useMutation } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ModelTypeEnum } from '@/app/components/header/account-setting/model-provider-page/declarations'
import {
  useModelListAndDefaultModelAndCurrentProviderAndModel,
} from '@/app/components/header/account-setting/model-provider-page/hooks'
import ModelParameterModal from '@/app/components/header/account-setting/model-provider-page/model-parameter-modal'
import { useHooksStore } from '@/app/components/workflow/hooks-store'
import { useStore, useWorkflowStore } from '@/app/components/workflow/store'
import { generateWorkflowFromPrd } from '@/service/debug'
import { EMPTY_WORKFLOW_GENERATOR_MODEL, useWorkflowGeneratorModel } from '../workflow-generator/storage'

const DEFAULT_TREE_TYPE = 'reasoning_action'

const phaseKeys = [
  'prdWorkflowGenerator.progress.context',
  'prdWorkflowGenerator.progress.plan',
  'prdWorkflowGenerator.progress.graph',
  'prdWorkflowGenerator.progress.validate',
  'prdWorkflowGenerator.progress.sync',
]

const closeButtonClassName = [
  'absolute top-4 right-4 cursor-pointer border-none bg-transparent p-2',
  'focus-visible:ring-1 focus-visible:ring-components-input-border-active focus-visible:outline-hidden',
].join(' ')

const dialogDescriptionClassName = [
  'w-full system-md-regular wrap-break-word whitespace-pre-wrap',
  'text-text-tertiary',
].join(' ')

async function resolveErrorCodeAndMessage(error: unknown): Promise<{ code?: string, message: string }> {
  if (error instanceof Response) {
    try {
      const data = await error.json() as { code?: string, message?: string, description?: string }
      return {
        code: data.code,
        message: data.message || data.description || data.code || '',
      }
    }
    catch {
      return { message: '' }
    }
  }
  if (error instanceof Error)
    return { message: error.message }
  return { message: String(error || '') }
}

export default function PrdWorkflowGenerator() {
  const { t } = useTranslation('workflow')
  const appId = useStore(s => s.appId)
  const draftHash = useStore(s => s.syncWorkflowDraftHash)
  const canEdit = useHooksStore(s => s.accessControl.canEdit)
  const handleRefreshWorkflowDraft = useHooksStore(s => s.handleRefreshWorkflowDraft)
  const workflowStore = useWorkflowStore()
  const [model, setModel] = useWorkflowGeneratorModel()
  const { defaultModel } = useModelListAndDefaultModelAndCurrentProviderAndModel(ModelTypeEnum.textGeneration)
  const [open, setOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [workspace, setWorkspace] = useState('')
  const [docId, setDocId] = useState('')
  const [treeType, setTreeType] = useState(DEFAULT_TREE_TYPE)
  const [forceRebuild, setForceRebuild] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])

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

  const mutation = useMutation({
    mutationFn: generateWorkflowFromPrd,
    onSuccess: (response) => {
      setWarnings(response.warnings || [])
      if (response.result !== 'success' || !response.draft_synced) {
        const message = response.warnings?.[0] || response.missing_requirements?.[0]
        toast.error(message || t('prdWorkflowGenerator.generateFailed'))
        return
      }
      toast.success(t('prdWorkflowGenerator.generated'))
      setOpen(false)
      handleRefreshWorkflowDraft()
    },
    onError: async (error) => {
      const { code, message } = await resolveErrorCodeAndMessage(error)
      const localized = code
        ? t(`prdWorkflowGenerator.errors.${code}`, { defaultValue: '' })
        : ''
      toast.error(localized || message || t('prdWorkflowGenerator.generateFailed'))
    },
  })

  const validate = useCallback(() => {
    if (!workspace.trim()) {
      toast.error(t('prdWorkflowGenerator.workspaceRequired'))
      return false
    }
    if (!docId.trim()) {
      toast.error(t('prdWorkflowGenerator.docIdRequired'))
      return false
    }
    if (!model.name || !model.provider) {
      toast.error(t('workflowGenerator.modelRequired'))
      return false
    }
    return true
  }, [docId, model.name, model.provider, t, workspace])

  const handleGenerateClick = useCallback(() => {
    if (!validate())
      return
    workflowStore.getState().flushPendingSync()
    setWarnings([])
    setConfirmOpen(true)
  }, [validate, workflowStore])

  const handleConfirmGenerate = useCallback(() => {
    setConfirmOpen(false)
    mutation.mutate({
      app_id: appId,
      source: {
        type: 'wiki_tree_context',
        doc_id: docId.trim(),
        workspace: workspace.trim(),
        tree_type: treeType.trim() || DEFAULT_TREE_TYPE,
        force_rebuild: forceRebuild,
      },
      model_config: {
        provider: model.provider,
        name: model.name,
        mode: model.mode || EMPTY_WORKFLOW_GENERATOR_MODEL.mode,
        completion_params: model.completion_params,
      },
      sync_to_draft: true,
      overwrite_policy: 'require_confirmation',
      ...(draftHash ? { draft_hash: draftHash } : {}),
    })
  }, [appId, docId, draftHash, forceRebuild, model, mutation, treeType, workspace])

  if (!canEdit)
    return null

  return (
    <>
      <Button
        size="small"
        variant="secondary"
        className="gap-1"
        onClick={() => setOpen(true)}
      >
        <RiFileTextLine className="size-4" aria-hidden="true" />
        <span>{t('prdWorkflowGenerator.trigger')}</span>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[560px] max-w-none! overflow-hidden! border-none p-0! text-left align-middle">
          <button
            type="button"
            className={closeButtonClassName}
            aria-label={t('operation.close', { ns: 'common' })}
            onClick={() => setOpen(false)}
          >
            <RiCloseLine className="size-4 text-text-tertiary" aria-hidden="true" />
          </button>
          <div className="px-6 pt-6 pb-5">
            <div className="title-2xl-semi-bold text-text-primary">
              {t('prdWorkflowGenerator.title')}
            </div>
            <div className="mt-5">
              <ModelParameterModal
                popupClassName="w-[520px]!"
                isAdvancedMode={true}
                provider={model.provider}
                completionParams={model.completion_params}
                modelId={model.name}
                setModel={handleModelChange}
                onCompletionParamsChange={handleCompletionParamsChange}
                hideDebugWithMultipleModel
              />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <label className="block">
                <div className="mb-1.5 system-sm-medium text-text-secondary">
                  {t('prdWorkflowGenerator.workspace')}
                </div>
                <Input
                  value={workspace}
                  onChange={e => setWorkspace(e.target.value)}
                  disabled={mutation.isPending}
                />
              </label>
              <label className="block">
                <div className="mb-1.5 system-sm-medium text-text-secondary">
                  {t('prdWorkflowGenerator.docId')}
                </div>
                <Input
                  value={docId}
                  onChange={e => setDocId(e.target.value)}
                  disabled={mutation.isPending}
                />
              </label>
              <label className="block">
                <div className="mb-1.5 system-sm-medium text-text-secondary">
                  {t('prdWorkflowGenerator.treeType')}
                </div>
                <Input
                  value={treeType}
                  onChange={e => setTreeType(e.target.value)}
                  disabled={mutation.isPending}
                />
              </label>
              <label className="mt-7 flex items-center gap-2 system-sm-medium text-text-secondary">
                <Checkbox
                  checked={forceRebuild}
                  onCheckedChange={checked => setForceRebuild(Boolean(checked))}
                  disabled={mutation.isPending}
                />
                <span>{t('prdWorkflowGenerator.forceRebuild')}</span>
              </label>
            </div>
            {mutation.isPending && (
              <div className="mt-5 rounded-lg bg-background-section-burn p-3">
                <div className="space-y-2">
                  {phaseKeys.map(key => (
                    <div key={key} className="flex items-center gap-2 system-xs-regular text-text-tertiary">
                      <span className="size-1.5 rounded-full bg-text-accent" />
                      <span>{t(key)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!!warnings.length && !mutation.isPending && (
              <div className="mt-5 rounded-lg bg-background-section-burn p-3 system-xs-regular text-text-tertiary">
                {warnings[0]}
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 border-t border-divider-subtle bg-background-section-burn px-6 py-4">
            <Button disabled={mutation.isPending} onClick={() => setOpen(false)}>
              {t('operation.cancel', { ns: 'common' })}
            </Button>
            <Button
              variant="primary"
              loading={mutation.isPending}
              disabled={!model.name || mutation.isPending}
              onClick={handleGenerateClick}
            >
              {t('prdWorkflowGenerator.generate')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <div className="flex flex-col gap-2 px-6 pt-6 pb-4">
            <AlertDialogTitle className="w-full truncate title-2xl-semi-bold text-text-primary">
              {t('prdWorkflowGenerator.overwriteTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className={dialogDescriptionClassName}>
              {t('prdWorkflowGenerator.overwriteMessage')}
            </AlertDialogDescription>
          </div>
          <AlertDialogActions>
            <AlertDialogCancelButton>{t('operation.cancel', { ns: 'common' })}</AlertDialogCancelButton>
            <AlertDialogConfirmButton onClick={handleConfirmGenerate}>
              {t('operation.confirm', { ns: 'common' })}
            </AlertDialogConfirmButton>
          </AlertDialogActions>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
