import { useCallback, useEffect, useRef, useState } from 'react'

/** Observations kept in the browser; older ones are dropped so memory stays bounded. */
export const MAX_HISTORY = 300
/** Live alerts kept in the browser (session-only, Phase 17); the oldest are dropped first. */
export const MAX_ALERTS = 200
const SEVERITY_RANK = { info: 0, attention: 1, significant: 2 }

/**
 * Parameters with an active live alert for one run (Phase 19A visual highlighting): unacknowledged, non-stale
 * alerts of `experimentId`, including co-occurrence parameters. Pure; derived from existing alert state.
 */
export function alertedParameters(alerts, experimentId) {
  const out = new Set()
  if (!experimentId) return out
  for (const a of alerts) {
    if (a.experiment_id !== experimentId || a.acknowledged || a.stale) continue
    if (a.finding.parameter) out.add(a.finding.parameter)
    for (const p of a.finding.related_parameters ?? []) out.add(p)
  }
  return out
}

/** Merge one alert event: "new" appends, "updated" replaces in place; an escalation needs acknowledging again. */
function mergeAlert(alerts, { alert }) {
  const i = alerts.findIndex((a) => a.alert_id === alert.alert_id && a.experiment_id === alert.experiment_id)
  if (i === -1) return [...alerts, { ...alert, received_at: Date.now(), acknowledged: false, stale: false }].slice(-MAX_ALERTS)
  const old = alerts[i]
  const escalated = SEVERITY_RANK[alert.finding.severity] > SEVERITY_RANK[old.finding.severity]
  const next = [...alerts]
  next[i] = { ...old, ...alert, acknowledged: old.acknowledged && !escalated, escalated: old.escalated || escalated }
  return next
}

const socketUrl = () =>
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/simulator/ws`

/** Connection to the backend's simulated bioreactor WebSocket (see backend/app/simulator_api.py). */
export function useSimulator() {
  const socketRef = useRef(null)
  const [connection, setConnection] = useState('connecting') // connecting | open | closed
  const [status, setStatus] = useState('stopped') // simulating | stopped
  const [run, setRun] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(null)
  const [saves, setSaves] = useState({ saved: 0, failed: 0, lastError: null })
  const [attempt, setAttempt] = useState(0)
  const [alerts, setAlerts] = useState([])

  useEffect(() => {
    const socket = new WebSocket(socketUrl())
    socketRef.current = socket
    setConnection('connecting')

    socket.onopen = () => setConnection('open')
    socket.onclose = () => {
      if (socketRef.current !== socket) return
      setConnection('closed')
      setStatus('stopped')
      // The run ended with the connection: keep its alerts visible but mark them stale.
      setAlerts((list) => list.map((a) => ({ ...a, stale: true })))
    }
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'observation') {
        setHistory((h) => [...h.slice(-(MAX_HISTORY - 1)), message.observation])
        if (message.saved === true) setSaves((s) => ({ ...s, saved: s.saved + 1 }))
        if (message.saved === false) setSaves((s) => ({ ...s, failed: s.failed + 1 }))
      } else if (message.type === 'status') {
        setStatus(message.status)
        setRun(message.run)
        if (!message.run) {
          setHistory([])
          setSaves({ saved: 0, failed: 0, lastError: null })
          setAlerts([])
        }
      } else if (message.type === 'alert') {
        setAlerts((list) => mergeAlert(list, message))
      } else if (message.type === 'persistence_error') {
        setSaves((s) => ({ ...s, lastError: message.message }))
      } else if (message.type === 'error') {
        setError(message.message)
      }
    }

    return () => {
      socketRef.current = null
      socket.close()
    }
  }, [attempt])

  const send = useCallback((message) => {
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) return
    setError(null)
    socket.send(JSON.stringify(message))
  }, [])

  return {
    connection,
    status,
    run,
    history,
    error,
    saves,
    alerts,
    unacknowledged: alerts.filter((a) => !a.acknowledged).length,
    /** Start (or resume) a run; `saveTo` stores every observation in that SIMULATED experiment. */
    start: (config, saveTo) => send({ action: 'start', config, save_to: saveTo || undefined }),
    stop: () => send({ action: 'stop' }),
    reset: () => send({ action: 'reset' }),
    reconnect: () => setAttempt((n) => n + 1),
    /** SIMULATED DISTURBANCE (Phase 17): step-shift one value of the current run to demonstrate live alerts. */
    disturb: (parameter, offset) => send({ action: 'disturb', parameter, offset }),
    acknowledge: (alertId) => setAlerts((list) => list.map((a) => (a.alert_id === alertId ? { ...a, acknowledged: true } : a))),
  }
}
