import { useEffect, useState } from 'react'
import { AlertTriangle, Save, X } from 'lucide-react'
import { getErrorMessage } from '../../services/api'
import {
  PRIORITY_LABELS,
  STATUS_LABELS,
  TICKET_PRIORITIES,
  TICKET_STATUSES,
  getTicket,
  updateTicket,
} from '../../services/tickets'
import { formatDateTime } from '../../utils/format'
import Button from '../ui/Button'
import Loader from '../ui/Loader'
import { PriorityBadge, StatusBadge } from './TicketBadges'

/**
 * Modal with one ticket, loaded from GET /api/tickets/{id}. Status and priority can be changed (PATCH).
 * Render it with key={ticketId} so each ticket starts from a clean loading state.
 */
export default function TicketDetails({ ticketId, onClose, onUpdated }) {
  const [ticket, setTicket] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [reloads, setReloads] = useState(0)
  const [edits, setEdits] = useState({}) // only fields the user changed: { status?, priority? }
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    getTicket(ticketId)
      .then((data) => {
        if (cancelled) return
        setTicket(data)
        setLoadError(null)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getErrorMessage(err, 'Could not load the ticket.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticketId, reloads])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function retry() {
    setLoading(true)
    setLoadError(null)
    setReloads((n) => n + 1)
  }

  const status = edits.status ?? ticket?.status
  const priority = edits.priority ?? ticket?.priority
  const changes = {}
  if (ticket && status !== ticket.status) changes.status = status
  if (ticket && priority !== ticket.priority) changes.priority = priority
  const dirty = Object.keys(changes).length > 0

  function edit(field, value) {
    setEdits((prev) => ({ ...prev, [field]: value }))
    setSaved(false)
    setSaveError(null)
  }

  async function save() {
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const updated = await updateTicket(ticket.id, changes)
      setTicket(updated)
      setEdits({})
      setSaved(true)
      onUpdated() // the list and counts behind the dialog reload from the backend
    } catch (err) {
      setSaveError(getErrorMessage(err, 'Could not update the ticket.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal card" role="dialog" aria-modal="true" aria-labelledby="ticket-dialog-title">
        <div className="modal-head">
          <h2 id="ticket-dialog-title">{ticket ? ticket.ticket_number : 'Ticket'}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close" autoFocus>
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        {loading && (
          <div className="library-state" role="status">
            <Loader size={22} />
            <p>Loading ticket…</p>
          </div>
        )}

        {!loading && loadError && (
          <div className="library-state" role="alert">
            <AlertTriangle size={26} aria-hidden="true" />
            <h3>Could not load this ticket</h3>
            <p>{loadError}</p>
            <div className="modal-actions">
              <Button variant="secondary" className="btn-sm" onClick={onClose}>Close</Button>
              <Button variant="secondary" className="btn-sm" onClick={retry}>Try again</Button>
            </div>
          </div>
        )}

        {!loading && !loadError && ticket && (
          <>
            <h3 className="ticket-detail-title">{ticket.title}</h3>
            <div className="ticket-detail-badges">
              <StatusBadge status={ticket.status} />
              <PriorityBadge priority={ticket.priority} />
            </div>

            <h4 className="detail-label">Description</h4>
            <p className="ticket-description">{ticket.description || 'No description provided.'}</p>

            <dl className="detail-grid">
              <div><dt>Category</dt><dd>{ticket.category || '—'}</dd></div>
              <div><dt>Created</dt><dd>{formatDateTime(ticket.created_at)}</dd></div>
              <div><dt>Updated</dt><dd>{formatDateTime(ticket.updated_at)}</dd></div>
            </dl>

            <div className="update-box">
              <h4 className="detail-label">Update ticket</h4>
              <div className="update-fields">
                <label className="field">
                  <span>Status</span>
                  <select value={status} onChange={(e) => edit('status', e.target.value)} disabled={saving}>
                    {TICKET_STATUSES.map((value) => <option key={value} value={value}>{STATUS_LABELS[value]}</option>)}
                  </select>
                </label>
                <label className="field">
                  <span>Priority</span>
                  <select value={priority} onChange={(e) => edit('priority', e.target.value)} disabled={saving}>
                    {TICKET_PRIORITIES.map((value) => <option key={value} value={value}>{PRIORITY_LABELS[value]}</option>)}
                  </select>
                </label>
              </div>

              {saveError && (
                <div className="banner banner-error" role="alert">
                  <AlertTriangle size={18} aria-hidden="true" />
                  <span>{saveError}</span>
                </div>
              )}
              {saved && (
                <div className="banner banner-ok" role="status">
                  <span>Ticket updated.</span>
                </div>
              )}

              <div className="modal-actions">
                <Button variant="secondary" className="btn-sm" onClick={onClose}>Close</Button>
                <Button className="btn-sm" onClick={save} disabled={!dirty || saving}>
                  {saving ? <Loader size={16} /> : <Save size={16} aria-hidden="true" />}
                  {saving ? 'Saving…' : 'Save changes'}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
