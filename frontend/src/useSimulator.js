import { useCallback, useEffect, useRef, useState } from 'react'

/** Observations kept in the browser; older ones are dropped so memory stays bounded. */
export const MAX_HISTORY = 300

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

  useEffect(() => {
    const socket = new WebSocket(socketUrl())
    socketRef.current = socket
    setConnection('connecting')

    socket.onopen = () => setConnection('open')
    socket.onclose = () => {
      if (socketRef.current !== socket) return
      setConnection('closed')
      setStatus('stopped')
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
        }
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
    /** Start (or resume) a run; `saveTo` stores every observation in that SIMULATED experiment. */
    start: (config, saveTo) => send({ action: 'start', config, save_to: saveTo || undefined }),
    stop: () => send({ action: 'stop' }),
    reset: () => send({ action: 'reset' }),
    reconnect: () => setAttempt((n) => n + 1),
  }
}
