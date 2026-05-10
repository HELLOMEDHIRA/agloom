/**
 * Observability API client — thin REST wrapper for the agloom observability backend.
 * Base URL: VITE_OBS_API_URL (default: http://localhost:8766)
 */

const BASE = (import.meta.env['VITE_OBS_API_URL'] ?? 'http://localhost:8766') + '/observe'

export interface SessionSummary {
  session_id:    string
  thread_id:     string | null
  started_at:    string
  ended_at:      string | null
  status:        'open' | 'closed' | 'error'
  pattern:       string | null
  total_turns:   number
  input_tokens:  number
  output_tokens: number
  duration_ms:   number | null
  total_events?: number
}

export interface EventRow {
  seq:    number
  type:   string
  ts:     string
  data:   Record<string, unknown>
  run_id: string | null
}

export interface ToolMetric {
  tool:              string
  call_count:        number
  total_duration_ms: number
  error_count:       number
  avg_duration_ms:   number
}

export interface NodeMetric {
  node:              string
  graph:             string | null
  call_count:        number
  total_duration_ms: number
  avg_duration_ms:   number
}

export interface TimelinePoint {
  ts:         string
  event_type: string
  label:      string
  duration_ms: number | null
  seq:        number
}

export interface SessionMetrics {
  session_id:          string
  total_events:        number
  total_turns:         number
  total_input_tokens:  number
  total_output_tokens: number
  session_duration_ms: number | null
  tools:               ToolMetric[]
  nodes:               NodeMetric[]
  timeline:            TimelinePoint[]
  transient_errors:    number
  fatal_errors:        number
  hitl_gates:          number
}

export interface GlobalSummary {
  total_sessions:           number
  open_sessions:            number
  total_turns:              number
  total_input_tokens:       number
  total_output_tokens:      number
  avg_session_duration_ms:  number
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const obsApi = {
  summary:    ()           => get<GlobalSummary>('/summary'),
  sessions:   (limit = 50) => get<SessionSummary[]>(`/sessions?limit=${limit}`),
  session:    (id: string) => get<SessionSummary>(`/sessions/${id}`),
  events:     (id: string, limit = 500, types?: string) =>
    get<EventRow[]>(`/sessions/${id}/events?limit=${limit}${types ? `&types=${types}` : ''}`),
  metrics:    (id: string) => get<SessionMetrics>(`/sessions/${id}/metrics`),
  graph:      (id: string) => get<EventRow[]>(`/sessions/${id}/graph`),
  workers:    (id: string) => get<EventRow[]>(`/sessions/${id}/workers`),
  replayUrl:  (id: string, speed = 1) => `${BASE}/sessions/${id}/replay?speed=${speed}`,
  liveUrl:    ()           => `${BASE}/live`,
}
