/**
 * ArtifactViewer — side panel showing all artifacts (code, markdown, JSON) generated
 * in the current session. Renders code with Monaco, markdown inline.
 */
import React, { useState } from 'react'
import Editor from '@monaco-editor/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { useSessionStore } from '../../store/session.js'
import { cn, truncate } from '../../lib/utils/cn.js'
import { Package, Copy, Check } from 'lucide-react'

export function ArtifactViewer(): React.ReactElement {
  const artifacts = useSessionStore((s) => s.artifacts)
  const [selected, setSelected] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const active = artifacts.find((a) => a.id === selected) ?? artifacts.at(-1)

  const copyContent = () => {
    if (!active) return
    navigator.clipboard.writeText(active.content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (artifacts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-neutral-600 text-sm p-6 text-center">
        <Package size={24} />
        <p>Artifacts appear here when the assistant generates code or documents.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Artifact list */}
      {artifacts.length > 1 && (
        <div className="flex flex-col gap-1 p-2 border-b border-neutral-800 max-h-32 overflow-y-auto">
          {artifacts.map((a) => (
            <button
              key={a.id}
              onClick={() => setSelected(a.id)}
              className={cn(
                'flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left transition-colors',
                active?.id === a.id ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'
              )}
            >
              <span className="text-neutral-600 font-mono">{a.type}</span>
              {a.language && <span className="text-indigo-400">.{a.language}</span>}
              <span className="truncate flex-1">{truncate(a.content.split('\n')[0] ?? '', 40)}</span>
            </button>
          ))}
        </div>
      )}

      {/* Active artifact */}
      {active && (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Toolbar */}
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-neutral-800 shrink-0">
            <span className="text-xs text-neutral-500 font-mono">
              {active.type}{active.language ? `.${active.language}` : ''}
            </span>
            <button
              onClick={copyContent}
              className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-300 transition-colors"
            >
              {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-hidden">
            {active.type === 'code' ? (
              <Editor
                height="100%"
                language={active.language ?? 'plaintext'}
                value={active.content}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  automaticLayout: true,
                }}
              />
            ) : active.type === 'markdown' ? (
              <div className="overflow-y-auto h-full p-4 prose prose-sm prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {active.content}
                </ReactMarkdown>
              </div>
            ) : (
              <pre className="overflow-auto h-full p-4 text-xs text-neutral-300 font-mono whitespace-pre-wrap">
                {active.content}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
