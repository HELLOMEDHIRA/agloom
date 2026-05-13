/** Prompt input: Enter to send, Shift+Enter newline, optional attachments. */
import React, { useRef, useState, useCallback } from 'react'
import { Send, StopCircle, CornerDownLeft, Paperclip } from 'lucide-react'
import { cn } from '../../lib/utils/cn.js'
import { useSessionStore } from '../../store/session.js'
import { fmtTokens } from '../../lib/utils/cn.js'
import type { AGPClient } from '../../lib/agp/client.js'
import { ModelPicker } from './ModelPicker.js'

interface Props {
  client: AGPClient
  workspaceSessionId: string
  onSubmit: (text: string) => void
  onCancel: () => void
  /** Fire-and-forget upload to runtime (`command.attach.file`). */
  onAttachFiles?: (files: File[]) => void
  pendingAttachmentPaths?: string[]
  disabled?: boolean
  isRunning?: boolean
}

export const ChatInput = ({
  client,
  workspaceSessionId,
  onSubmit,
  onCancel,
  onAttachFiles,
  pendingAttachmentPaths = [],
  disabled,
  isRunning,
}: Props): React.ReactElement => {
  const [value, setValue] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)

  const submit = useCallback(() => {
    const t = value.trim()
    if (!t || isRunning) return
    onSubmit(t)
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, isRunning, onSubmit])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      e.key === 't' &&
      !e.ctrlKey &&
      !e.metaKey &&
      !e.altKey &&
      value === '' &&
      !disabled &&
      !isRunning
    ) {
      e.preventDefault()
      useSessionStore.getState().toggleActiveTurnToolExpandBulk()
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const autoResize = () => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, 180)}px`
    }
  }

  const pushFiles = (files: FileList | File[]) => {
    if (!onAttachFiles || disabled || isRunning) return
    const arr = Array.from(files)
    if (arr.length === 0) return
    onAttachFiles(arr)
  }

  return (
    <div
      className={cn(
        'border-t border-neutral-200 bg-neutral-50 px-4 py-3 shrink-0 transition-colors',
        'dark:border-neutral-800 dark:bg-neutral-950',
        dragOver && 'bg-indigo-100/80 ring-1 ring-indigo-400/50 dark:bg-indigo-950/40 dark:ring-indigo-500/40',
      )}
      onDragEnter={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setDragOver(true)
      }}
      onDragLeave={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setDragOver(false)
      }}
      onDragOver={(e) => {
        e.preventDefault()
        e.stopPropagation()
      }}
      onDrop={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setDragOver(false)
        pushFiles(e.dataTransfer.files)
      }}
    >
      {/* Token / model info */}
      <div className="flex flex-wrap items-center gap-2 mb-2 text-xs text-neutral-600 dark:text-neutral-500">
        <ModelPicker client={client} workspaceSessionId={workspaceSessionId} />
        {totalIn + totalOut > 0 ? <span>{fmtTokens(totalIn)}↑ {fmtTokens(totalOut)}↓</span> : null}
      </div>

      {pendingAttachmentPaths.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {pendingAttachmentPaths.map((p) => (
            <span
              key={p}
              className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-indigo-100 text-indigo-900 border border-indigo-200 max-w-full truncate dark:bg-indigo-950/80 dark:text-indigo-200 dark:border-indigo-800/60"
              title={p}
            >
              {p}
            </span>
          ))}
        </div>
      )}

      <div className={cn(
        'flex items-end gap-2 rounded-xl border px-3 py-2 transition-colors',
        disabled || isRunning
          ? 'border-neutral-200 bg-neutral-100/80 dark:border-neutral-800 dark:bg-neutral-900/50'
          : 'border-neutral-300 bg-white focus-within:border-indigo-500 dark:border-neutral-700 dark:bg-neutral-900 dark:focus-within:border-indigo-600',
      )}>
        <input
          ref={fileRef}
          type="file"
          multiple
          aria-label="Attach files"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) pushFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled || isRunning}
          className={cn(
            'p-1.5 rounded-lg shrink-0 self-end mb-0.5 transition-colors',
            disabled || isRunning
              ? 'text-neutral-400 cursor-not-allowed dark:text-neutral-700'
              : 'text-neutral-500 hover:text-indigo-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:text-indigo-300 dark:hover:bg-neutral-800',
          )}
          title="Attach files"
        >
          <Paperclip size={16} />
        </button>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); autoResize() }}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          placeholder={
            disabled        ? 'Waiting for HITL approval…'
            : isRunning     ? 'Running… press ⌘+K to cancel'
            : 'Message agloom…'
          }
          className={cn(
            'flex-1 resize-none bg-transparent text-sm text-neutral-900 placeholder-neutral-400 focus:outline-none leading-relaxed',
            'dark:text-white dark:placeholder-neutral-600 max-h-45 overflow-y-auto',
          )}
        />

        <div className="flex items-center gap-1.5 pb-0.5">
          {/* Cancel when running */}
          {isRunning && (
            <button onClick={onCancel} className="p-1.5 text-red-400 hover:text-red-300 transition-colors" title="Cancel (⌘K)">
              <StopCircle size={16} />
            </button>
          )}

          {/* Send */}
          <button
            onClick={submit}
            disabled={!value.trim() || isRunning || disabled}
            className={cn(
              'p-1.5 rounded-lg transition-colors',
              value.trim() && !isRunning && !disabled
                ? 'text-indigo-600 hover:text-indigo-500 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:text-indigo-300 dark:hover:bg-indigo-950/50'
                : 'text-neutral-400 cursor-not-allowed dark:text-neutral-700',
            )}
            title="Send (Enter)"
          >
            <Send size={15} />
          </button>
        </div>
      </div>

      <p className="text-xs text-neutral-500 dark:text-neutral-700 mt-1.5 text-center">
        <CornerDownLeft size={9} className="inline mr-0.5" />Enter to send · Shift+Enter for newline
      </p>
    </div>
  )
}
