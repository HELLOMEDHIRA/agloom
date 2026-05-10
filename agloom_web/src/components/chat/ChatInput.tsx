/**
 * ChatInput — the primary chat input bar.
 * Supports multi-line (Shift+Enter), submit on Enter, cancel while running.
 */
import React, { useRef, useState, useCallback } from 'react'
import { Send, StopCircle, CornerDownLeft } from 'lucide-react'
import { cn } from '../../lib/utils/cn.js'
import { useSessionStore } from '../../store/session.js'
import { fmtTokens } from '../../lib/utils/cn.js'

interface Props {
  onSubmit: (text: string) => void
  onCancel: () => void
  disabled?: boolean
  isRunning?: boolean
}

export function ChatInput({ onSubmit, onCancel, disabled, isRunning }: Props): React.ReactElement {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)
  const model = useSessionStore((s) => s.model)

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

  return (
    <div className="border-t border-neutral-800 bg-neutral-950 px-4 py-3 shrink-0">
      {/* Token / model info */}
      {(totalIn + totalOut > 0 || model) && (
        <div className="flex items-center gap-3 mb-2 text-xs text-neutral-600">
          {model && <span>{model}</span>}
          {totalIn + totalOut > 0 && <span>{fmtTokens(totalIn)}↑ {fmtTokens(totalOut)}↓</span>}
        </div>
      )}

      <div className={cn(
        'flex items-end gap-2 rounded-xl border px-3 py-2 transition-colors',
        disabled || isRunning
          ? 'border-neutral-800 bg-neutral-900/50'
          : 'border-neutral-700 bg-neutral-900 focus-within:border-indigo-600',
      )}>
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
            'flex-1 resize-none bg-transparent text-sm text-white placeholder-neutral-600 focus:outline-none leading-relaxed',
            'max-h-[180px] overflow-y-auto',
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
                ? 'text-indigo-400 hover:text-indigo-300 hover:bg-indigo-950/50'
                : 'text-neutral-700 cursor-not-allowed',
            )}
            title="Send (Enter)"
          >
            <Send size={15} />
          </button>
        </div>
      </div>

      <p className="text-xs text-neutral-700 mt-1.5 text-center">
        <CornerDownLeft size={9} className="inline mr-0.5" />Enter to send · Shift+Enter for newline
      </p>
    </div>
  )
}
