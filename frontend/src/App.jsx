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

const PAGES = [
  { id: 'command-center', label: 'Command Center', Component: CommandCenter },
  { id: 'experiment-data', label: 'Experiment Data', Component: ExperimentData },
  { id: 'simulator', label: 'Simulated Bioreactor', Component: SimulatedBioreactor },
  { id: 'bioreactor', label: 'Bioreactor', Component: BioreactorVisualization },
  { id: 'monitoring', label: 'Process Monitoring', Component: ProcessMonitoring },
  { id: 'anomalies', label: 'Anomalies', Component: AnomalyDetection },
  { id: 'forecasting', label: 'Forecasting', Component: ProcessForecasting },
  { id: 'planning', label: 'Experiment Planning', Component: ExperimentPlanning },
  { id: 'scaleup', label: 'Scale-Up', Component: ScaleUpSimulator },
  { id: 'ai', label: 'AI Analysis', Component: AIProcessAnalysis },
  { id: 'copilot', label: 'AI Copilot', Component: AICopilot },
  { id: 'comparison', label: 'Experiment Comparison', Component: ExperimentComparison },
  { id: 'report', label: 'Report', Component: ReportGeneration },
  { id: 'history', label: 'Experiment History', Component: ExperimentHistory },
  { id: 'status', label: 'Backend Status', Component: BackendStatus },
]

export default function App() {
  const [pageId, setPageId] = useState('experiment-data')
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
          {PAGES.map((p) => (
            <button
              key={p.id}
              className={`tab ${p.id === pageId ? 'tab-active' : ''}`}
              aria-current={p.id === pageId ? 'page' : undefined}
              onClick={() => setPageId(p.id)}
            >
              {p.label}
            </button>
          ))}
        </nav>
      </header>

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
