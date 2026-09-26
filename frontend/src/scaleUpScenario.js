import { getExperimentAnalysis } from './api.js'

export const SCENARIO_SCALES = [10, 100, 1000]

// Scale-up targets kept at the source's latest values (Phase 6 "preserved" scenario).
const TARGET_FIELDS = {
  temperature_c: 'target_temperature_c',
  ph: 'target_ph',
  dissolved_oxygen_percent: 'target_dissolved_oxygen_percent',
  agitation_rpm: 'target_agitation_rpm',
  aeration_rate: 'target_aeration_vvm',
  feed_rate: 'target_feed_rate_ml_per_h',
}

/** Scale-up scenario that keeps the experiment's latest recorded values at `targetScale` litres. */
export async function buildPreservedScaleUp(experimentId, targetScale) {
  const source = await getExperimentAnalysis(experimentId)
  const scenario = { source_experiment_id: experimentId, target_scale_liters: targetScale }
  for (const p of source.parameters) if (TARGET_FIELDS[p.parameter]) scenario[TARGET_FIELDS[p.parameter]] = p.final
  return scenario
}
