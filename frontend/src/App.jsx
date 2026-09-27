import { useCallback, useState } from 'react'
import AICopilot from './components/AICopilot.jsx'
import AIProcessAnalysis from './components/AIProcessAnalysis.jsx'
import AnomalyDetection from './components/AnomalyDetection.jsx'
import BackendStatus from './components/BackendStatus.jsx'
import BioreactorVisualization from './components/BioreactorVisualization.jsx'
import CommandCenter from './components/CommandCenter.jsx'
import ExperimentComparison from './components/ExperimentComparison.jsx'
import ExperimentData from './components/ExperimentData.jsx'
import ExperimentHistory from './components/ExperimentHistory.jsx'
import ExperimentPlanning from './components/ExperimentPlanning.jsx'
import ProcessForecasting from './components/ProcessForecasting.jsx'
import ProcessMonitoring from './components/ProcessMonitoring.jsx'
import ReportGeneration from './components/ReportGeneration.jsx'
import ScaleUpSimulator from './components/ScaleUpSimulator.jsx'
import SimulatedBioreactor from './components/SimulatedBioreactor.jsx'
import { useSimulator } from './useSimulator.js'

// `group`, `purpose` and `stage` are presentation only (UI/UX Phases 2 and 9; `stage` = step in the demo investigation story): navigation groups follow the existing tab order.
const PAGES = [
  { id: 'command-center', stage: '1 · Monitor', label: 'Command Center', Component: CommandCenter, group: 'Operate', purpose: 'Operational overview of the selected experiment or live simulated run.' },
  { id: 'experiment-data', label: 'Experiment Data', Component: ExperimentData, group: 'Operate', purpose: 'Create experiments and record observations manually or from CSV.' },
  { id: 'simulator', stage: '1 · Monitor', label: 'Simulated Bioreactor', Component: SimulatedBioreactor, group: 'Operate', purpose: 'Run the software simulator, inject simulated disturbances and review live alerts.' },
  { id: 'bioreactor', stage: '1 · Monitor', label: 'Bioreactor', Component: BioreactorVisualization, group: 'Operate', purpose: 'Illustrative view of the simulated bioreactor state.' },
  { id: 'monitoring', stage: '1 · Monitor', label: 'Process Monitoring', Component: ProcessMonitoring, group: 'Operate', purpose: 'Track process variables across the culture timeline.' },
  { id: 'anomalies', stage: '2 · Investigate', label: 'Anomalies', Component: AnomalyDetection, group: 'Investigate', purpose: 'Review rule-based process findings, their evidence and precedents in stored runs.' },
  { id: 'forecasting', stage: '5 · Forecast', label: 'Forecasting', Component: ProcessForecasting, group: 'Model & Plan', purpose: 'Explore model-based estimates from historical observations.' },
  { id: 'planning', stage: '6 · Plan', label: 'Experiment Planning', Component: ExperimentPlanning, group: 'Model & Plan', purpose: 'Explore candidate conditions based on existing observations and allowed ranges.' },
  { id: 'scaleup', stage: '4 · Scale', label: 'Scale-Up', Component: ScaleUpSimulator, group: 'Model & Plan', purpose: 'Evaluate deterministic scale relationships, engineering assumptions and stored scale-up series.' },
  { id: 'ai', stage: '7 · Ask AI', label: 'AI Analysis', Component: AIProcessAnalysis, group: 'AI & Output', purpose: 'Gemini interpretation of the deterministic analysis, generated only on request.' },
  { id: 'copilot', stage: '7 · Ask AI', label: 'AI Copilot', Component: AICopilot, group: 'AI & Output', purpose: 'Ask questions about the selected experiment and its available evidence.' },
  { id: 'comparison', stage: '3 · Compare', label: 'Experiment Comparison', Component: ExperimentComparison, group: 'AI & Output', purpose: 'Compare two stored experiments side by side.' },
  { id: 'report', stage: '8 · Report', label: 'Report', Component: ReportGeneration, group: 'AI & Output', purpose: 'Generate a PDF report from existing results.' },
  { id: 'history', label: 'Experiment History', Component: ExperimentHistory, group: 'Records', purpose: 'Browse, open and delete stored experiments.' },
  { id: 'status', label: 'Backend Status', Component: BackendStatus, group: 'Records', purpose: 'Backend connection and AI configuration status.' },
]
// Consecutive pages with the same group, in tab order (the order of PAGES is unchanged).
const GROUPS = PAGES.reduce((groups, page) => {
  const last = groups.at(-1)
  if (last?.name === page.group) last.pages.push(page)
  else groups.push({ name: page.group, pages: [page] })
  return groups
}, [])

export default function App() {
  const [pageId, setPageId] = useState('command-center')
  const current = PAGES.find((p) => p.id === pageId)
  // The single simulator WebSocket, shared by the Simulated Bioreactor page and the Bioreactor view.
  const sim = useSimulator()
  // Bumped whenever stored experiments change, so every page can reload its lists.
  const [dataVersion, setDataVersion] = useState(0)
  const onDataChanged = useCallback(() => setDataVersion((v) => v + 1), [])
  // Set by "Analyze" in Experiment History; a new object each time so it re-triggers.
  const [analysisRequest, setAnalysisRequest] = useState(null)
  // Latest AI Process Analysis per experiment (in memory only), so the Copilot can optionally include it.
  const [aiAnalyses, setAIAnalyses] = useState({})
  const onAIAnalysis = useCallback((experimentId, result) => setAIAnalyses((m) => ({ ...m, [experimentId]: result })), [])
  // Latest Scale-Up scenario request and Copilot answer per experiment (in memory only), for the report.
  const [scaleUpScenarios, setScaleUpScenarios] = useState({})
  const onScaleUpScenario = useCallback((experimentId, request) => setScaleUpScenarios((m) => ({ ...m, [experimentId]: request })), [])
  const [copilotReplies, setCopilotReplies] = useState({})
  const onCopilotReply = useCallback((experimentId, reply) => setCopilotReplies((m) => ({ ...m, [experimentId]: reply })), [])
  // Latest forecast settings per experiment (in memory only), so the Copilot can optionally include the forecast.
  const [forecastSettings, setForecastSettings] = useState({})
  const onForecastSettings = useCallback((experimentId, body) => setForecastSettings((m) => ({ ...m, [experimentId]: body })), [])
  // Set by "Compare with this run" (Phase 18 precedents); a new object each time so it re-triggers.
  const [comparisonRequest, setComparisonRequest] = useState(null)
  const openComparison = useCallback((experimentAId, experimentBId) => {
    setComparisonRequest({ experimentAId, experimentBId })
    setPageId('comparison')
  }, [])
  const openAnalysis = useCallback((experimentId) => {
    setAnalysisRequest({ experimentId })
    setPageId('monitoring')
  }, [])

  return (
    <main className="container">
      <header>
        <h1>AI Copilot for Scalable Cell-Culture Bioprocess Design</h1>
        <p className="subtitle">
          Decision support for analysing bioreactor data and scale-up. No physical
          bioreactor is connected.
        </p>
        <nav className="tabs" aria-label="Main">
          {GROUPS.map((g) => (
            <div key={g.name} className="tab-group" role="group" aria-label={g.name}>
              <span className="tab-group-label" aria-hidden="true">
                {g.name}
              </span>
              <div className="tab-group-items">
                {g.pages.map((p) => (
                  <button
                    key={p.id}
                    className={`tab ${p.id === pageId ? 'tab-active' : ''}`}
                    aria-current={p.id === pageId ? 'page' : undefined}
                    onClick={() => setPageId(p.id)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </header>
      {current && (
        <p className="page-context" aria-live="polite" data-stage={current.stage}>
          <span className="page-context-group">{current.group}</span>
          <span className="page-context-sep" aria-hidden="true">
            ›
          </span>
          <strong>{current.label}</strong>
          <span className="page-context-purpose"> — {current.purpose}</span>
        </p>
      )}

      {/* All pages stay mounted so switching tabs keeps their state (e.g. a running simulation). */}
      {PAGES.map(({ id, Component }) => (
        <div key={id} hidden={id !== pageId}>
          <Component
            active={id === pageId}
            sim={sim}
            onNavigate={setPageId}
            dataVersion={dataVersion}
            onDataChanged={onDataChanged}
            analysisRequest={analysisRequest}
            onOpenAnalysis={openAnalysis}
            comparisonRequest={comparisonRequest}
            onOpenComparison={openComparison}
            aiAnalyses={aiAnalyses}
            onAIAnalysis={onAIAnalysis}
            scaleUpScenarios={scaleUpScenarios}
            onScaleUpScenario={onScaleUpScenario}
            copilotReplies={copilotReplies}
            onCopilotReply={onCopilotReply}
            forecastSettings={forecastSettings}
            onForecastSettings={onForecastSettings}
          />
        </div>
      ))}
    </main>
  )
}
