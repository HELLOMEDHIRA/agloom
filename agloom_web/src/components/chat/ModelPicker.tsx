/**
 * Dropdown of curated providers (`command.providers.list` → `runtime.providers`).
 */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils/cn.js'
import { useSessionStore } from '../../store/session.js'
import type { AGPClient } from '../../lib/agp/client.js'

interface Props {
  client: AGPClient
  workspaceSessionId: string
}

const modelStorageKey = (sid: string) => `agloom-model-${sid}`

export const ModelPicker = ({ client, workspaceSessionId }: Props): React.ReactElement => {
  const providerCatalog = useSessionStore((s) => s.providerCatalog)
  const model = useSessionStore((s) => s.model)
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const listboxId = useId()

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    if (open && !providerCatalog) client.listProviders()
  }, [open, providerCatalog, client])

  const groups = useMemo(() => {
    const rows = providerCatalog ?? []
    const m = new Map<string, typeof rows>()
    for (const r of rows) {
      const ch = (r.label || r.slug).charAt(0).toUpperCase()
      const key = /[A-Z]/.test(ch) ? ch : '#'
      if (!m.has(key)) m.set(key, [])
      m.get(key)!.push(r)
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [providerCatalog])

  const apply = useCallback(
    (modelId: string) => {
      try {
        localStorage.setItem(modelStorageKey(workspaceSessionId), modelId)
      } catch {
        /* ignore */
      }
      client.send({ type: 'command.config.set', data: { model_id: modelId } })
      setOpen(false)
    },
    [client, workspaceSessionId],
  )

  const label = model?.trim() || 'Model'
  const triggerClassName = cn(
    'flex items-center gap-1 max-w-[220px] truncate rounded-md border px-2 py-1 text-xs font-mono',
    'border-neutral-300 bg-neutral-100 text-neutral-800 hover:bg-neutral-200',
    'dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-200 dark:hover:bg-neutral-800',
  )
  const triggerLabel = `Model: ${label}. Open provider list.`
  const toggleOpen = () => setOpen((o) => !o)
  const triggerFace = (
    <>
      <span className="truncate">{label}</span>
      <ChevronDown size={12} className="shrink-0 opacity-70" />
    </>
  )

  return (
    <div className="relative shrink-0" ref={rootRef}>
      {open ? (
        <button
          type="button"
          aria-expanded="true"
          aria-controls={listboxId}
          aria-haspopup="listbox"
          aria-label={triggerLabel}
          onClick={toggleOpen}
          className={triggerClassName}
        >
          {triggerFace}
        </button>
      ) : (
        <button
          type="button"
          aria-expanded="false"
          aria-controls={listboxId}
          aria-haspopup="listbox"
          aria-label={triggerLabel}
          onClick={toggleOpen}
          className={triggerClassName}
        >
          {triggerFace}
        </button>
      )}
      <ul
        id={listboxId}
        hidden={!open}
        className={cn(
          'absolute bottom-full left-0 z-50 mb-1 max-h-64 min-w-[260px] overflow-y-auto rounded-lg border py-1 shadow-xl',
          'border-neutral-200 bg-white text-neutral-900',
          'dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100',
        )}
        role="listbox"
      >
          {groups.length === 0 && (
            <li className="px-3 py-2 text-xs text-neutral-500">Loading providers…</li>
          )}
          {groups.map(([letter, rows]) => (
            <li key={letter} className="py-1">
              <div className="px-3 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-400">
                {letter}
              </div>
              {rows.map((r) => {
                const mid = `${r.slug}:${r.default_model}`
                return (
                  <button
                    key={`${r.slug}-${r.default_model}`}
                    type="button"
                    role="option"
                    className={cn(
                      'flex w-full flex-col items-start gap-0.5 px-3 py-1.5 text-left text-xs hover:bg-neutral-100',
                      'dark:hover:bg-neutral-800',
                    )}
                    onClick={() => apply(mid)}
                  >
                    <span className="font-medium text-neutral-800 dark:text-neutral-100">{r.label}</span>
                    <span className="font-mono text-[10px] text-neutral-500 dark:text-neutral-400">{mid}</span>
                  </button>
                )
              })}
            </li>
          ))}
      </ul>
    </div>
  )
}
