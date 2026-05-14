/**
 * First paint: credential preflight (fast fail), then workspace bootstrap (including optional
 * ``agsuperbrain init``), then ``bridge.start`` so AGP replay is buffered until {@link App}
 * mounts and subscribes.
 */

import React, { useEffect, useState } from 'react'
import { Box, Text } from 'ink'
import { App } from './App.js'
import { useSpinner } from '../hooks/useSpinner.js'
import { ensureAgloomCliWorkspace } from '../workspaceBootstrap.js'
import { preflightProviderCredentials } from '../utils/preflightProviderCredentials.js'
import type { AGPBridge } from '../runtime/bridge.js'

export interface BootstrapGateProps {
  bridge: AGPBridge
  cwd: string
  configPath?: string
  runtimeArgs: string[]
  /** Effective model id from CLI + YAML (used for credential preflight). */
  modelForPreflight: string
  providerForPreflight?: string | null
  initialThread: string
  showDiag?: boolean
  multiline?: boolean
  historyFile?: string
  /** Shown in sidebar until AGP session envelope arrives (``--session``). */
  cliSessionId?: string | null
}

type Phase = 'boot' | 'ready' | 'error'

export const BootstrapGate = ({
  bridge,
  cwd,
  configPath,
  runtimeArgs,
  modelForPreflight,
  providerForPreflight,
  ...appProps
}: BootstrapGateProps): React.ReactElement => {
  const [phase, setPhase] = useState<Phase>('boot')
  const [bootMessage, setBootMessage] = useState('Checking API credentials…')
  const [bootKind, setBootKind] = useState<'preflight' | 'workspace'>('preflight')
  const [errorText, setErrorText] = useState<string | null>(null)
  const spin = useSpinner(90)

  useEffect(() => {
    let cancelled = false

    const run = async (): Promise<void> => {
      try {
        setBootKind('preflight')
        setBootMessage('Checking API credentials…')
        const pf = preflightProviderCredentials(modelForPreflight, providerForPreflight)
        if (!pf.ok) {
          setErrorText(pf.message)
          setPhase('error')
          return
        }
        if (cancelled) return

        setBootKind('workspace')
        setBootMessage('Preparing workspace (Super-Brain may download on first run)…')
        await ensureAgloomCliWorkspace(cwd, { configPath })
        if (cancelled) return

        process.stderr.write('Starting agloom-runtime…\n')
        bridge.start(runtimeArgs, { transport: 'stdio' })
        setPhase('ready')
      } catch (e) {
        if (cancelled) return
        setErrorText(e instanceof Error ? e.message : String(e))
        setPhase('error')
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [bridge, cwd, configPath, runtimeArgs, modelForPreflight, providerForPreflight])

  if (phase === 'error' && errorText) {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text color="red" bold>
          Cannot start agloom
        </Text>
        {errorText.split('\n').map((line, i) => (
          <Text key={i} color="red">
            {line}
          </Text>
        ))}
        <Box marginTop={1}>
          <Text dimColor>Press Ctrl+C to exit.</Text>
        </Box>
      </Box>
    )
  }

  if (phase !== 'ready') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text color="cyan">
          {spin} {bootMessage}
        </Text>
        <Box marginTop={1}>
          <Text dimColor>
            {bootKind === 'preflight'
              ? 'Verifying provider credentials for the selected model.'
              : 'First launch can take a few minutes while Super-Brain indexes the project.'}
          </Text>
        </Box>
      </Box>
    )
  }

  return <App bridge={bridge} {...appProps} />
}
