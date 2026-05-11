/**
 * Diff for edit_file / multi_edit: prefer wire `resultDiff`, else arg old/new; uses react-diff-viewer-continued.
 */
import React, { memo, useState } from 'react'
import ReactDiffViewer from 'react-diff-viewer-continued'
import { diffLines } from 'diff'
import type { ToolCall } from '../../store/session.js'
import { cn } from '../../lib/utils/cn.js'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useUiTheme } from '../../lib/theme.js'

interface Props {
  toolCall: ToolCall
}

export const EditFileDiff = memo(({ toolCall }: Props): React.ReactElement | null => {
  const { effective } = useUiTheme()
  const [open, setOpen] = useState(true)
  const { tool, args, resultDiff } = toolCall
  const oldStr =
    resultDiff?.before
    ?? (typeof args['old_string'] === 'string' ? args['old_string'] : null)
  const newStr =
    resultDiff?.after
    ?? (typeof args['new_string'] === 'string' ? args['new_string'] : null)
  if (oldStr == null || newStr == null) return null
  if (tool !== 'edit_file' && tool !== 'multi_edit' && tool !== 'write_file') return null

  const path = typeof args['path'] === 'string' ? args['path'] : undefined
  const lang = resultDiff?.language || (typeof args['language'] === 'string' ? args['language'] : undefined)

  const useViewer = Boolean(resultDiff) && oldStr.length + newStr.length < 400_000

  if (!useViewer) {
    const lines = diffLines(oldStr, newStr)
    return (
      <div className="mt-1 rounded-lg border border-neutral-200 bg-neutral-50/80 overflow-hidden text-[11px] font-mono leading-snug dark:border-neutral-800 dark:bg-neutral-950/80">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1 w-full px-2 py-1.5 text-left text-neutral-500 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-900/80"
        >
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span>diff</span>
          {path && <span className="text-indigo-500 dark:text-indigo-400 truncate">{path}</span>}
        </button>
        {open && (
          <div className="max-h-48 overflow-auto px-2 py-1 border-t border-neutral-200 dark:border-neutral-800">
            {lines.map((part, i) => (
              <span
                key={i}
                className={cn(
                  'whitespace-pre-wrap break-all',
                  part.added && 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-100',
                  part.removed && 'bg-red-100 text-red-900 dark:bg-red-950/50 dark:text-red-100',
                  !part.added && !part.removed && 'text-neutral-500 dark:text-neutral-400',
                )}
              >
                {part.value}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="mt-1 rounded-lg border border-neutral-200 bg-white overflow-hidden dark:border-neutral-800 dark:bg-neutral-950">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 w-full px-2 py-1.5 text-left text-xs text-neutral-500 hover:bg-neutral-50 dark:text-neutral-400 dark:hover:bg-neutral-900/80"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>diff</span>
        {path && <span className="text-indigo-500 dark:text-indigo-400 truncate font-mono text-[11px]">{path}</span>}
        {lang ? <span className="text-[10px] text-neutral-400">· {lang}</span> : null}
      </button>
      {open && (
        <div className="max-h-[min(70vh,520px)] overflow-auto border-t border-neutral-200 dark:border-neutral-800 text-xs [&_.diff-viewer]:text-xs">
          <ReactDiffViewer
            oldValue={oldStr}
            newValue={newStr}
            splitView
            useDarkTheme={effective === 'dark'}
            showDiffOnly={false}
          />
        </div>
      )}
    </div>
  )
})

EditFileDiff.displayName = 'EditFileDiff'
