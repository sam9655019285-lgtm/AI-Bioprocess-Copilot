import { useState } from 'react'
import { alertedParameters } from '../useSimulator.js'
import BioreactorVessel from './BioreactorVessel.jsx'

const NA = 'Not available'
const SCALES = [1, 10, 100, 1000]
// Speed = how often the existing simulator steps (interval_seconds); culture time per step is unchanged.
const SPEEDS = [
  { label: '0.5×', interval: 2 },
  { label: '1×', interval: 1 },
  { label: '2×', interval: 0.5 },
  { label: '5×', interval: 0.2 },
]

const METRICS = [
  { key: 'temperature_c', label: 'Temperature', unit: '°C', digits: 1, help: 'Culture temperature (simulated)' },
  { key: 'ph', label: 'pH', unit: '', digits: 2, help: 'Acidity of the culture medium (simulated)' },
  { key: 'dissolved_oxygen_percent', label: 'DO', unit: '% air sat.', digits: 1, help: 'Dissolved oxygen: oxygen availability in the culture' },
  { key: 'agitation_rpm', label: 'Agitation', unit: 'rpm', digits: 0, help: 'Agitation: controls mixing' },
  { key: 'cell_density', label: 'Cell density', unit: '×10⁶ cells/mL', digits: 2, help: 'Cell density: simulated viable cell concentration' },
  { key: 'feed_rate', label: 'Feed', unit: 'mL/h', digits: 2, help: 'Feed: nutrient/media addition' },
  { key: 'nutrient_concentration', label: 'Nutrient', unit: 'g/L', digits: 2, help: 'Nutrient concentration in the medium (simulated)' },
  { key: 'aeration_rate', label: 'Aeration', unit: 'vvm', digits: 3, help: 'Aeration: gas flow into the reactor' },
  { key: 'culture_time_hours', label: 'Culture time', unit: 'h', digits: 1, help: 'Simulated time since inoculation' },
]

const LEGEND = [
  ['Impeller', 'Agitation: controls mixing'],
  ['Bubbles', 'Aeration: gas flow into the reactor'],
  ['Feed line', 'Feed: nutrient/media addition'],
  ['Particles', 'Cell density: simulated viable cell concentration'],
  ['DO / pH probes', 'Dissolved oxygen: oxygen availability in the culture'],
]

const format = (value, digits, unit) => (value == null ? NA : `${value.toFixed(digits)}${unit ? ` ${unit}` : ''}`)

function statusOf(sim) {
  if (sim.connection === 'closed') return { id: 'error', label: 'Error' }
  if (sim.connection === 'connecting') return { id: 'stopped', label: 'Connecting' }
  if (sim.status === 'simulating') return { id: 'running', label: 'Running' }
  return sim.run ? { id: 'paused', label: 'Paused' } : { id: 'stopped', label: 'Stopped' }
}

/** Interactive, illustrative view of the existing Phase 3 simulator (same state, same WebSocket). */
export default function BioreactorVisualization({ sim, active, scaleUpScenarios = {} }) {
  const [volume, setVolume] = useState(1)
  const [interval, setIntervalSeconds] = useState(1)
  const latest = sim.history.at(-1) ?? null
  const status = statusOf(sim)
  const connected = sim.connection === 'open'
  const running = status.id === 'running'
  const run = sim.run
  const runInterval = run?.interval_seconds ?? interval
  const scenario = run?.saving_to ? scaleUpScenarios[run.saving_to] : null
  const shownVolume = run ? run.volume_liters : volume

  function handleStart() {
    // Resume keeps the existing run; a new run here is preview-only with default initial conditions.
    sim.start(run ? {} : { volume_liters: volume, interval_seconds: interval })
  }

  return (
    <section className="card bioreactor-page">
      <div className="sim-header">
        <div>
          <h2>Bioreactor Visualization</h2>
          <div className="source-badge">Data Source: SIMULATED BIOREACTOR</div>
        </div>
        <span className={`bx-status bx-status-${status.id}`} role="status" data-testid="bx-status">
          <span className="dot" aria-hidden="true" />
          {status.label}
        </span>
      </div>
      <div className="alert alert-warning bx-notice">
        <strong>Illustrative simulation — not a real-time physical bioreactor measurement.</strong> Visual elements
        represent simulated process values and are not calibrated physical measurements.
      </div>
      {sim.connection === 'closed' && (
        <div className="alert alert-error">
          Disconnected from the simulator. Is the FastAPI server running on port 8000?{' '}
          <button className="secondary small" onClick={sim.reconnect}>
            Reconnect
          </button>
        </div>
      )}
      {sim.error && <div className="alert alert-error">{sim.error}</div>}

      <div className="bx-layout">
        <figure className="bx-figure">
          {active && (
            <BioreactorVessel values={latest} running={running} volumeLiters={shownVolume} highlight={alertedParameters(sim.alerts, run?.experiment_id)} />
          )}
          <figcaption className="muted small-note">
            Cell visualization — illustrative. Particles, bubbles, mixing arrows and drops are symbolic and scaled from
            the simulator values; they are not a cell count, oxygen-transfer or flow model.
          </figcaption>
        </figure>

        <div className="bx-panel">
          <h3>Live bioprocess data</h3>
          <dl className="bx-metrics" aria-label="Live simulated process values">
            {METRICS.map((m) => (
              <div key={m.key} className="bx-metric" title={m.help} data-testid={`bx-${m.key}`}>
                <dt>{m.label}</dt>
                <dd>{format(latest?.[m.key], m.digits, m.unit)}</dd>
              </div>
            ))}
          </dl>

          <div className="bx-gauges">
            <div className="bx-gauge" title="Dissolved oxygen: oxygen availability in the culture">
              <span className="muted small-label">DO (0–100 % scale)</span>
              <div className="bx-bar">
                <span style={{ width: `${Math.min(latest?.dissolved_oxygen_percent ?? 0, 100)}%` }} />
              </div>
            </div>
            <div className="bx-gauge" title="pH marker on a 6–8 display scale">
              <span className="muted small-label">pH (6–8 display scale)</span>
              <div className="bx-bar bx-ph">
                {latest?.ph != null && <i style={{ left: `${Math.min(Math.max((latest.ph - 6) / 2, 0), 1) * 100}%` }} />}
              </div>
            </div>
          </div>

          <h3>Scale</h3>
          {scenario ? (
            <p className="bx-scale" data-testid="bx-scale">
              Source <strong>{run.volume_liters} L</strong> → target <strong>{scenario.target_scale_liters} L</strong> ·
              scale factor <strong>{Number((scenario.target_scale_liters / run.volume_liters).toFixed(3))}×</strong>
              <span className="muted small-note"> (scenario from the Scale-Up page)</span>
            </p>
          ) : (
            <p className="bx-scale" data-testid="bx-scale">
              Working volume <strong>{shownVolume} L</strong>
              {run?.saving_to && <span className="muted"> · experiment {run.saving_to}</span>}
            </p>
          )}
          {!run && (
            <div className="chip-group" aria-label="Working volume for a new run">
              {SCALES.map((s) => (
                <button type="button" key={s} className={`chip ${volume === s ? 'chip-active' : ''}`} onClick={() => setVolume(s)}>
                  {s} L
                </button>
              ))}
            </div>
          )}
          <p className="muted small-note">The drawing is the same size at every scale; it does not represent vessel dimensions.</p>
        </div>
      </div>

      <div className="bx-controls">
        <div className="actions">
          <button onClick={handleStart} disabled={!connected || running}>
            ▶ {run ? 'Resume' : 'Start'}
          </button>
          <button className="secondary" onClick={sim.stop} disabled={!connected || !running}>
            ⏸ Pause
          </button>
          <button className="secondary" onClick={sim.reset} disabled={!connected || !run}>
            ↻ Reset
          </button>
        </div>
        <div className="bx-speed">
          <span className="muted small-label">Speed</span>
          <div className="chip-group" aria-label="Simulation speed">
            {SPEEDS.map((s) => (
              <button
                type="button"
                key={s.label}
                className={`chip ${runInterval === s.interval ? 'chip-active' : ''}`}
                disabled={Boolean(run)}
                onClick={() => setIntervalSeconds(s.interval)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <p className="muted small-note">
        Start here runs a preview with default initial conditions (not saved); set initial conditions or save to an
        experiment on the Simulated Bioreactor tab — both tabs show the same run. Speed changes how often the simulator
        steps (each step is still {run?.hours_per_step ?? 0.5} h of culture time) and applies to new runs.
        {run && ` Current run: ${run.experiment_id}${run.saving_to ? ' (saving)' : ' (preview only)'}.`}
      </p>

      <ul className="bx-legend">
        {LEGEND.map(([k, v]) => (
          <li key={k}>
            <strong>{k}:</strong> {v}
          </li>
        ))}
      </ul>
    </section>
  )
}
