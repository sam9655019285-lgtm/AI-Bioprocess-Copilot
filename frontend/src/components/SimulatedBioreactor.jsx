import { useEffect, useRef, useState } from 'react'
import { getObservationSchema } from '../api.js'
import { MAX_HISTORY } from '../useSimulator.js'
import ExperimentPicker from './ExperimentPicker.jsx'
import MetricCard from './MetricCard.jsx'
import ObservationTable from './ObservationTable.jsx'
import TrendChart from './TrendChart.jsx'

const VOLUMES = [1, 10, 100, 1000]

const DEFAULT_CONFIG = {
  volume_liters: 1,
  temperature_c: '37',
  ph: '7.1',
  dissolved_oxygen_percent: '50',
  agitation_rpm: '180',
  cell_density: '0.5',
}

const CONFIG_FIELDS = [
  { name: 'temperature_c', label: 'Initial temperature', unit: '°C' },
  { name: 'ph', label: 'Initial pH', unit: '' },
  { name: 'dissolved_oxygen_percent', label: 'Initial DO', unit: '% air sat.' },
  { name: 'agitation_rpm', label: 'Initial agitation', unit: 'rpm' },
  { name: 'cell_density', label: 'Initial cell density', unit: '×10⁶ cells/mL' },
]

const METRICS = [
  { key: 'temperature_c', label: 'Temperature', unit: '°C', digits: 2 },
  { key: 'ph', label: 'pH', unit: '', digits: 2 },
  { key: 'dissolved_oxygen_percent', label: 'Dissolved Oxygen', unit: '% air sat.', digits: 1 },
  { key: 'agitation_rpm', label: 'Agitation', unit: 'rpm', digits: 0 },
  { key: 'cell_density', label: 'Cell Density', unit: '×10⁶ cells/mL', digits: 2 },
  { key: 'culture_time_hours', label: 'Culture Time', unit: 'h', digits: 1 },
]

const CHARTS = [
  { dataKey: 'temperature_c', title: 'Temperature', unit: '°C', digits: 2, minSpan: 1 },
  { dataKey: 'ph', title: 'pH', unit: '', digits: 2, minSpan: 0.2 },
  { dataKey: 'dissolved_oxygen_percent', title: 'Dissolved oxygen', unit: '% air sat.', digits: 1, minSpan: 10 },
  { dataKey: 'cell_density', title: 'Cell density', unit: '×10⁶ cells/mL', digits: 2, minSpan: 1 },
]

const RECENT_ROWS = 10
const TABLE_EXCLUDE = new Set(['feed_rate', 'notes'])

/** `sim` is the app-wide simulator connection (useSimulator in App), shared with the Bioreactor view. */
export default function SimulatedBioreactor({ sim, active, dataVersion, onDataChanged }) {
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const [experiment, setExperiment] = useState(null) // stored SIMULATED experiment to save into, or null
  const [fields, setFields] = useState(null)

  useEffect(() => {
    getObservationSchema()
      .then((f) => setFields(f.filter((field) => !TABLE_EXCLUDE.has(field.name))))
      .catch(() => setFields(null))
  }, [])

  // A saved run's experiment now holds data, so after a reset (from this page or the Bioreactor view)
  // a new saved run needs a new experiment.
  const savingTo = useRef(null)
  useEffect(() => {
    if (sim.run) {
      savingTo.current = sim.run.saving_to
    } else if (savingTo.current) {
      savingTo.current = null
      setExperiment(null)
      onDataChanged?.()
    }
  }, [sim.run, onDataChanged])

  const simulating = sim.status === 'simulating'
  const connected = sim.connection === 'open'
  const latest = sim.history.at(-1)
  const recent = sim.history.slice(-RECENT_ROWS).reverse()

  function handleStart() {
    // When saving, the stored experiment defines the scale.
    const payload = experiment ? {} : { volume_liters: Number(config.volume_liters) }
    for (const { name } of CONFIG_FIELDS) payload[name] = Number(config[name])
    sim.start(payload, experiment?.experiment_id)
  }

  function handleStop() {
    sim.stop()
    onDataChanged?.()
  }

  function handleReset() {
    sim.reset()
    onDataChanged?.()
  }

  return (
    <section className="card sim">
      <div className="sim-header">
        <div>
          <h2>Simulated Bioreactor</h2>
          <div className="source-badge">Data Source: SIMULATED BIOREACTOR</div>
        </div>
        <span className={`status-pill ${simulating ? 'status-running' : ''}`} role="status">
          <span className="dot" aria-hidden="true" />
          {simulating ? 'SIMULATING' : 'STOPPED'}
        </span>
      </div>
      <p className="muted disclaimer">
        Software-only simulation for demonstration, testing and visualisation. Values come from a simple
        illustrative model, not from laboratory equipment, and are not experimental measurements.
      </p>

      {sim.connection !== 'open' && (
        <div className="alert alert-error">
          {sim.connection === 'connecting'
            ? 'Connecting to the simulator…'
            : 'Disconnected from the simulator. Is the FastAPI server running on port 8000?'}{' '}
          {sim.connection === 'closed' && (
            <button className="secondary small" onClick={sim.reconnect}>
              Reconnect
            </button>
          )}
        </div>
      )}
      {sim.error && <div className="alert alert-error">{sim.error}</div>}
      {sim.saves.lastError && (
        <div className="alert alert-warning" role="status">
          {sim.saves.failed} observation(s) could not be saved. Last error: {sim.saves.lastError}
        </div>
      )}

      <div className="sim-controls">
        <div className="sim-save-to">
          <h3>Save to experiment</h3>
          <ExperimentPicker
            sources={['simulated']}
            value={experiment}
            onChange={setExperiment}
            onCreated={onDataChanged}
            version={dataVersion}
            disabled={Boolean(sim.run)}
            noneLabel="— Don't save (preview only) —"
          />
        </div>

        <fieldset disabled={Boolean(sim.run)} className="config-grid">
          <legend className="visually-hidden">Initial conditions</legend>
          <label className="field">
            <span>Culture volume</span>
            {experiment ? (
              <input value={`${experiment.scale_liters} L (from experiment)`} readOnly />
            ) : (
              <select
                value={config.volume_liters}
                onChange={(e) => setConfig({ ...config, volume_liters: e.target.value })}
              >
                {VOLUMES.map((v) => (
                  <option key={v} value={v}>
                    {v} L
                  </option>
                ))}
              </select>
            )}
          </label>
          {CONFIG_FIELDS.map((f) => (
            <label key={f.name} className="field">
              <span>{f.label}</span>
              <span className="input-with-unit">
                <input
                  type="number"
                  step="any"
                  value={config[f.name]}
                  onChange={(e) => setConfig({ ...config, [f.name]: e.target.value })}
                />
                {f.unit && <span className="unit">{f.unit}</span>}
              </span>
            </label>
          ))}
        </fieldset>

        <div className="actions">
          <button onClick={handleStart} disabled={!connected || simulating}>
            {sim.run && !simulating ? 'RESUME' : 'START'}
          </button>
          <button className="secondary" onClick={handleStop} disabled={!connected || !simulating}>
            STOP
          </button>
          <button className="secondary" onClick={handleReset} disabled={!connected || !sim.run}>
            RESET
          </button>
        </div>
        {sim.run && (
          <p className="muted run-info">
            Run <strong>{sim.run.experiment_id}</strong> · {sim.run.volume_liters} L (volume is metadata only) ·
            1 s ≈ {sim.run.hours_per_step} h culture time. Reset to change initial conditions.
            <br />
            {sim.run.saving_to ? (
              <span className="saving-info">
                Saving to <strong>{sim.run.saving_to}</strong> · {sim.saves.saved} observation(s) saved
                {sim.saves.failed > 0 && `, ${sim.saves.failed} failed`}
              </span>
            ) : (
              'Preview only — observations are not saved.'
            )}
          </p>
        )}
      </div>

      <div className="metrics">
        {METRICS.map((m) => (
          <MetricCard key={m.key} label={m.label} value={latest?.[m.key]} unit={m.unit} digits={m.digits} />
        ))}
      </div>

      <h3>Live trends</h3>
      {sim.history.length === 0 ? (
        <p className="muted placeholder">Press START to begin streaming simulated data.</p>
      ) : (
        active && (
          <>
            <div className="charts">
              {CHARTS.map((c) => (
                <TrendChart key={c.dataKey} data={sim.history} {...c} />
              ))}
            </div>
            <p className="muted small-note">
              Showing the latest {sim.history.length} of max {MAX_HISTORY} observations kept in the browser.
            </p>
          </>
        )
      )}

      {fields && recent.length > 0 && (
        <ObservationTable title="Recent observations (newest first)" fields={fields} observations={recent} />
      )}
    </section>
  )
}
