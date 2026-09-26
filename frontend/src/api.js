/** Turn FastAPI's error `detail` (a string or a list of field errors) into one readable message. */
function describeError(status, detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = e.loc?.slice(1).join('.')
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join('; ')
  }
  if (status >= 500) return `The backend is unavailable (HTTP ${status}). Is the FastAPI server running on port 8000?`
  return `Backend responded with HTTP ${status}`
}

/** Error from the backend. `detail` is FastAPI's error detail (a string or a list of field errors). */
export class ApiError extends Error {
  constructor(status, detail) {
    super(describeError(status, detail))
    this.status = status
    this.detail = detail
  }
}

async function request(path, options) {
  let response
  try {
    response = await fetch(path, options)
  } catch {
    throw new ApiError(0, 'Network request failed')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(response.status, body?.detail)
  }
  return body
}

const json = (method, data) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

const fileForm = (file) => {
  const form = new FormData()
  form.append('file', file)
  return { method: 'POST', body: form }
}

const experimentPath = (experimentId) => `/api/experiments/${encodeURIComponent(experimentId)}`

// Health
export function getHealth() {
  return request('/api/health')
}

// Observation schema and validation-only endpoints (Phase 2)
export function getObservationSchema() {
  return request('/api/experiments/schema')
}

export function submitObservation(observation) {
  return request('/api/experiments/observations', json('POST', observation))
}

export function uploadObservationsCsv(file) {
  return request('/api/experiments/upload', fileForm(file))
}

// Stored experiments (Phase 4)
export function listExperiments() {
  return request('/api/experiments')
}

export function getExperiment(experimentId) {
  return request(experimentPath(experimentId))
}

export function createExperiment(experiment) {
  return request('/api/experiments', json('POST', experiment))
}

export function deleteExperiment(experimentId) {
  return request(experimentPath(experimentId), { method: 'DELETE' })
}

export function getExperimentObservations(experimentId, limit = 1000) {
  return request(`${experimentPath(experimentId)}/observations?limit=${limit}`)
}

export function getExperimentAnalysis(experimentId) {
  return request(`${experimentPath(experimentId)}/analysis`)
}

export function getExperimentAnomalies(experimentId) {
  return request(`${experimentPath(experimentId)}/anomalies`)
}

export function addExperimentObservation(experimentId, observation) {
  return request(`${experimentPath(experimentId)}/observations`, json('POST', observation))
}

export function uploadExperimentCsv(experimentId, file) {
  return request(`${experimentPath(experimentId)}/upload`, fileForm(file))
}

// Scale-up scenarios (Phase 6; read-only, illustrative)
export function simulateScaleUp(scenario) {
  return request('/api/scale-up/simulate', json('POST', scenario))
}

// AI process analysis (Phase 8; Gemini is called by the backend, the key never reaches the browser)
export function getAIStatus() {
  return request('/api/ai/status')
}

export function analyzeWithAI(experimentId, body = {}) {
  return request(`${experimentPath(experimentId)}/ai-analysis`, json('POST', body))
}

// AI Copilot (Phase 9): one question about one experiment; answered by the backend from deterministic context
export function askCopilot(experimentId, body) {
  return request(`${experimentPath(experimentId)}/copilot`, json('POST', body))
}

// Experiment comparison (Phase 10): deterministic, read-only; Gemini interpretation is optional
export function compareExperiments(experimentAId, experimentBId) {
  return request('/api/experiments/compare', json('POST', { experiment_a_id: experimentAId, experiment_b_id: experimentBId }))
}

export function interpretComparison(experimentAId, experimentBId) {
  return request('/api/experiments/compare/interpret', json('POST', { experiment_a_id: experimentAId, experiment_b_id: experimentBId }))
}

// Experiment report (Phase 11): returns the PDF as a Blob; optional sections go in the body
export async function generateReport(experimentId, body = {}) {
  let response
  try {
    response = await fetch(`${experimentPath(experimentId)}/report`, json('POST', body))
  } catch {
    throw new ApiError(0, 'Network request failed')
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new ApiError(response.status, detail?.detail)
  }
  return response.blob()
}
