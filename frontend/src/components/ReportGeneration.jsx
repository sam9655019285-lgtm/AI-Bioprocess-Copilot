import { useEffect, useState } from 'react'
import { generateReport, getAIStatus, getExperimentAnalysis, getExperimentAnomalies } from '../api.js'
import { buildPreservedScaleUp, SCENARIO_SCALES } from '../scaleUpScenario.js'
import ExperimentPicker from './ExperimentPicker.jsx'
import SourceBadge from './SourceBadge.jsx'

const SECTIONS = [
  'Executive Overview',
  'Experiment Details',
  'Process Statistics',
  'Process Trends',
  'Data Quality',
  'Anomaly / Findings',
  'Scale-Up Scenario (optional)',
  'AI Analysis (optional)',
  'AI Copilot (optional)',
  'Limitations',
]

const hours = (h) => (h == null ? '—' : `${Number(h.toFixed(2))} h`)
const filenameFor = (id) => `bioprocess-report-${id.replace(/[^A-Za-z0-9._-]/g, '_')}.pdf`

/** Downloadable PDF report built from existing results; Gemini is never required. */
export default function ReportGeneration({ active, dataVersion, aiAnalyses = {}, scaleUpScenarios = {}, copilotReplies = {} }) {
  const [experiment, setExperiment] = useState(null)
  const [preview, setPreview] = useState(null) // { analysis, anomalies }
  const [previewError, setPreviewError] = useState(null)
  const [configured, setConfigured] = useState(null)
  const [includeScaleUp, setIncludeScaleUp] = useState(false)
  const [targetScale, setTargetScale] = useState(100)
  const [includeAI, setIncludeAI] = useState(true)
  const [includeCopilot, setIncludeCopilot] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [download, setDownload] = useState(null) // { url, filename, size, experimentId }
  const [error, setError] = useState(null)
  const experimentId = experiment?.experiment_id
  const pageScenario = experimentId ? scaleUpScenarios[experimentId] : null
  const ai = experimentId ? aiAnalyses[experimentId] : null
  const copilot = experimentId ? copilotReplies[experimentId] : null

  useEffect(() => {
    if (!active) return
    getAIStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(null))
  }, [active])

  useEffect(() => {
    setError(null)
    if (!experimentId) {
      setPreview(null)
      return
    }
    if (!active) return
    let cancelled = false
    Promise.all([getExperimentAnalysis(experimentId), getExperimentAnomalies(experimentId)])
      .then(([analysis, anomalies]) => {
        if (cancelled) return
        setPreview({ analysis, anomalies })
        setPreviewError(null)
      })
      .catch((err) => !cancelled && setPreviewError(`Could not load the experiment: ${err.message}`))
    return () => {
      cancelled = true
    }
  }, [experimentId, active, dataVersion])

  // Free the previous file when a new one is made or the page goes away.
  useEffect(() => () => download && URL.revokeObjectURL(download.url), [download])

  async function handleGenerate() {
    setGenerating(true)
    setError(null)
    try {
      const body = {}
      if (includeScaleUp) body.scale_up = pageScenario ?? (await buildPreservedScaleUp(experimentId, targetScale))
      if (includeAI && ai) body.ai_analysis = ai
      if (includeCopilot && copilot) body.copilot = copilot
      const blob = await generateReport(experimentId, body)
      const url = URL.createObjectURL(blob)
      const filename = filenameFor(experimentId)
      setDownload({ url, filename, size: blob.size, experimentId, sections: Object.keys(body) })
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
    } catch (err) {
      setError(`The report could not be generated: ${err.message}`)
    } finally {
      setGenerating(false)
    }
  }

  const shown = preview?.analysis.experiment.experiment_id === experimentId ? preview : null
  const a = shown?.analysis
  const counts = shown?.anomalies.counts
  const shownDownload = download?.experimentId === experimentId ? download : null

  return (
    <section className="card report-page">
      <div className="card-header">
        <h2>Report Generation</h2>
        <span className="treat-badge treat-na" data-testid="ai-status">
          {configured == null ? 'Checking Gemini…' : configured ? 'Gemini configured (not required)' : 'Gemini not configured (not required)'}
        </span>
      </div>
      <p className="muted disclaimer">
        Generates a PDF from the application's existing results: process statistics, trends, data quality and anomaly
        findings, plus optional sections. Gemini is not called. Reports are created on demand and not stored.
      </p>

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={(e) => {
          setExperiment(e)
          setIncludeScaleUp(false)
        }}
        version={dataVersion}
        allowCreate={false}
      />
      {!experimentId && <p className="muted placeholder">Select an experiment to prepare its report.</p>}
      {previewError && <div className="alert alert-error">{previewError}</div>}
      {experimentId && !shown && !previewError && <p className="muted">Loading experiment…</p>}

      {shown && (
        <>
          <h3>Report contents</h3>
          <dl className="exp-facts copilot-context report-preview">
            <div>
              <dt>Experiment</dt>
              <dd>{a.experiment.experiment_id}</dd>
            </div>
            <div>
              <dt>Scale</dt>
              <dd>{a.experiment.scale_liters} L</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>
                <SourceBadge source={a.experiment.data_source} />
              </dd>
            </div>
            <div>
              <dt>Observations</dt>
              <dd>{a.observation_count}</dd>
            </div>
            <div>
              <dt>Culture duration</dt>
              <dd>{hours(a.culture_duration_hours)}</dd>
            </div>
            <div>
              <dt>Findings</dt>
              <dd>
                {shown.anomalies.finding_count} ({counts.significant} significant · {counts.attention} attention · {counts.info} info)
              </dd>
            </div>
          </dl>
          {a.observation_count === 0 && (
            <div className="alert alert-warning">
              This experiment has no observations. The report will say so, show “Not available” for statistics and
              “Insufficient data for trend” for the charts.
            </div>
          )}
          {a.experiment.data_source === 'simulated' && (
            <p className="muted small-note">The report will state that this experiment contains simulated (software-generated) data.</p>
          )}
          <ol className="report-sections">
            {SECTIONS.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>

          <h3>Optional sections</h3>
          <div className="report-options">
            <div className="report-option">
              <label className="ai-checkbox">
                <input type="checkbox" checked={includeScaleUp} onChange={(e) => setIncludeScaleUp(e.target.checked)} />
                Scale-Up Scenario
              </label>
              {pageScenario ? (
                <span className="muted small-note">
                  Uses the scenario simulated on the Scale-Up page ({a.experiment.scale_liters} L → {pageScenario.target_scale_liters} L).
                </span>
              ) : (
                <span className="muted small-note report-inline">
                  No Scale-Up page scenario for this experiment; a scenario keeping the latest values will be used at
                  <span className="chip-group" aria-label="Target scale">
                    {SCENARIO_SCALES.map((s) => (
                      <button type="button" key={s} className={`chip ${targetScale === s ? 'chip-active' : ''}`} onClick={() => setTargetScale(s)} disabled={!includeScaleUp}>
                        {s} L
                      </button>
                    ))}
                  </span>
                </span>
              )}
            </div>
            <div className="report-option">
              <label className="ai-checkbox">
                <input type="checkbox" checked={Boolean(ai) && includeAI} disabled={!ai} onChange={(e) => setIncludeAI(e.target.checked)} />
                AI Analysis
              </label>
              <span className="muted small-note">
                {ai
                  ? `AI Process Analysis from ${new Date(ai.generated_at).toLocaleTimeString()} (labelled as AI-generated interpretation).`
                  : 'Not available: no AI Process Analysis for this experiment in this session (optional; see the AI Analysis tab).'}
              </span>
            </div>
            <div className="report-option">
              <label className="ai-checkbox">
                <input type="checkbox" checked={Boolean(copilot) && includeCopilot} disabled={!copilot} onChange={(e) => setIncludeCopilot(e.target.checked)} />
                AI Copilot
              </label>
              <span className="muted small-note">
                {copilot
                  ? `Latest Copilot response: “${copilot.question}” (labelled as AI-generated).`
                  : 'Not available: no Copilot response for this experiment in this session (optional; see the AI Copilot tab).'}
              </span>
            </div>
          </div>

          <div className="actions">
            <button onClick={handleGenerate} disabled={generating}>
              {generating ? 'Generating PDF…' : 'Generate PDF report'}
            </button>
          </div>
          {generating && (
            <div className="ai-loading" role="status">
              <span className="spinner" aria-hidden="true" /> Generating the report for {experimentId}…
            </div>
          )}
          {error && <div className="alert alert-error">{error}</div>}
          {shownDownload && !generating && (
            <div className="alert alert-success report-success" role="status">
              Report generated: <strong>{shownDownload.filename}</strong> ({Math.max(1, Math.round(shownDownload.size / 1024))} KB)
              {shownDownload.sections.length > 0 && ` with ${shownDownload.sections.map((s) => s.replace('_', ' ')).join(', ')}`}.{' '}
              <a href={shownDownload.url} download={shownDownload.filename} data-testid="report-download">
                Download again
              </a>
            </div>
          )}
        </>
      )}
    </section>
  )
}
