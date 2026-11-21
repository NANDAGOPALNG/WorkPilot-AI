import { PRIORITY_LABELS, STATUS_LABELS } from '../../services/tickets'

// Reuses the existing .pill styles. Unknown values are shown as-is in a neutral style.
const STATUS_TONE = { open: 'pending', in_progress: 'warn', resolved: 'ok', closed: 'neutral' }
const PRIORITY_TONE = { low: 'neutral', medium: 'pending', high: 'warn', critical: 'error' }

export function StatusBadge({ status }) {
  return (
    <span className={`pill pill-${STATUS_TONE[status] ?? 'neutral'}`}>
      <i aria-hidden="true" />
      {STATUS_LABELS[status] ?? (status ? String(status) : 'Unknown')}
    </span>
  )
}

export function PriorityBadge({ priority }) {
  return (
    <span className={`pill pill-${PRIORITY_TONE[priority] ?? 'neutral'}`}>
      <i aria-hidden="true" />
      {PRIORITY_LABELS[priority] ?? (priority ? String(priority) : 'Unknown')}
    </span>
  )
}
