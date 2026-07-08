'use client'

import { Button } from '@langgenius/dify-ui/button'
import { RiSparkling2Line } from '@remixicon/react'
import { useTranslation } from 'react-i18next'
import { useHooksStore } from '@/app/components/workflow/hooks-store'
import { useStore } from '@/app/components/workflow/store'

export default function WorkflowNlEditAssistantTrigger() {
  const { t } = useTranslation('workflow')
  const canEdit = useHooksStore(s => s.accessControl.canEdit)
  const showNlEditAssistantPanel = useStore(s => s.showNlEditAssistantPanel)
  const setShowNlEditAssistantPanel = useStore(s => s.setShowNlEditAssistantPanel)

  if (!canEdit)
    return null

  return (
    <Button
      size="small"
      variant={showNlEditAssistantPanel ? 'primary' : 'secondary'}
      className="gap-1"
      onClick={() => setShowNlEditAssistantPanel(!showNlEditAssistantPanel)}
    >
      <RiSparkling2Line className="size-4" aria-hidden="true" />
      <span>{t('workflowGraphEdit.trigger')}</span>
    </Button>
  )
}
