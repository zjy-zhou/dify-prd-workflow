import type { HeaderProps } from '@/app/components/workflow/header'
import {
  memo,
  useCallback,
  useMemo,
} from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore as useAppStore } from '@/app/components/app/store'
import WorkflowNlEditAssistantTrigger from '@/app/components/workflow/nl-edit-assistant/trigger'
import WorkflowPackageExport from '@/app/components/workflow/package-export'
import PrdWorkflowGenerator from '@/app/components/workflow/prd-workflow-generator'
import Header from '@/app/components/workflow/header'
import { useResetWorkflowVersionHistory } from '@/service/use-workflow'
import { useIsChatMode } from '../../hooks'
import ChatVariableTrigger from './chat-variable-trigger'
import FeaturesTrigger from './features-trigger'

const WorkflowHeader = () => {
  const { appDetail, setCurrentLogItem, setShowMessageLogModal } = useAppStore(useShallow(state => ({
    appDetail: state.appDetail,
    setCurrentLogItem: state.setCurrentLogItem,
    setShowMessageLogModal: state.setShowMessageLogModal,
  })))
  const resetWorkflowVersionHistory = useResetWorkflowVersionHistory()
  const isChatMode = useIsChatMode()

  const handleClearLogAndMessageModal = useCallback(() => {
    setCurrentLogItem()
    setShowMessageLogModal(false)
  }, [setCurrentLogItem, setShowMessageLogModal])

  const viewHistoryProps = useMemo(() => {
    return {
      onClearLogAndMessageModal: handleClearLogAndMessageModal,
      historyUrl: isChatMode ? `/apps/${appDetail!.id}/advanced-chat/workflow-runs` : `/apps/${appDetail!.id}/workflow-runs`,
    }
  }, [appDetail, isChatMode, handleClearLogAndMessageModal])

  const headerProps: HeaderProps = useMemo(() => {
    return {
      normal: {
        components: {
          middle: (
            <>
              <PrdWorkflowGenerator />
              <WorkflowNlEditAssistantTrigger />
              <WorkflowPackageExport />
              <FeaturesTrigger />
            </>
          ),
          chatVariableTrigger: <ChatVariableTrigger />,
        },
        runAndHistoryProps: {
          showRunButton: !isChatMode,
          showPreviewButton: isChatMode,
          viewHistoryProps,
        },
      },
      viewHistory: {
        viewHistoryProps,
      },
      restoring: {
        onRestoreSettled: resetWorkflowVersionHistory,
      },
    }
  }, [resetWorkflowVersionHistory, isChatMode, viewHistoryProps])
  return (
    <Header {...headerProps} />
  )
}

export default memo(WorkflowHeader)
