export const SOURCE_LABELS = { manual: 'MANUAL', csv: 'CSV', simulated: 'SIMULATED' }

export default function SourceBadge({ source }) {
  return <span className={`src-badge src-${source}`}>{SOURCE_LABELS[source] ?? source.toUpperCase()}</span>
}
