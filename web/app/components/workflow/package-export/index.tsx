'use client'

import { Button } from '@langgenius/dify-ui/button'
import { toast } from '@langgenius/dify-ui/toast'
import { RiDownload2Line } from '@remixicon/react'
import { useMutation } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useHooksStore } from '@/app/components/workflow/hooks-store'
import { useStore } from '@/app/components/workflow/store'
import { exportWorkflowPackage, useAppWorkflow } from '@/service/use-workflow'
import { downloadBlob } from '@/utils/download'

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

export default function WorkflowPackageExport() {
  const { t } = useTranslation('workflow')
  const appID = useStore(s => s.appId)
  const publishedAt = useStore(s => s.publishedAt)
  const canReleaseAndVersion = useHooksStore(s => s.accessControl.canReleaseAndVersion)
  const { data: publishedWorkflow, isLoading } = useAppWorkflow(appID)
  const workflowID = publishedWorkflow?.id

  const mutation = useMutation({
    mutationFn: () => exportWorkflowPackage(appID, workflowID!),
    onSuccess: ({ data, fileName }) => {
      downloadBlob({ data, fileName })
      toast.success(t('prdWorkflowPackage.downloaded'))
    },
    onError: async (error) => {
      const message = await resolveErrorMessage(error)
      toast.error(message || t('prdWorkflowPackage.downloadFailed'))
    },
  })

  const handleDownload = useCallback(() => {
    if (!workflowID)
      return
    mutation.mutate()
  }, [mutation, workflowID])

  if (!canReleaseAndVersion || !publishedAt)
    return null

  return (
    <Button
      size="small"
      variant="secondary"
      className="gap-1"
      disabled={!workflowID || isLoading || mutation.isPending}
      loading={mutation.isPending}
      title={!workflowID ? t('prdWorkflowPackage.unpublished') : undefined}
      onClick={handleDownload}
    >
      <RiDownload2Line className="size-4" aria-hidden="true" />
      <span>{t('prdWorkflowPackage.trigger')}</span>
    </Button>
  )
}
