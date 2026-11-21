import { useState } from 'react'
import { AlertTriangle, ChevronLeft, ChevronRight, RefreshCw, Search, Ticket } from 'lucide-react'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Loader from '../components/ui/Loader'
import TicketDetails from '../components/tickets/TicketDetails'
import TicketTable from '../components/tickets/TicketTable'
import { PAGE_SIZE, useTickets } from '../hooks/useTickets'
import {
  PRIORITY_LABELS,
  STATUS_LABELS,
  TICKET_PRIORITIES,
  TICKET_STATUSES,
} from '../services/tickets'

const STAT_TONE = { open: 'pending', in_progress: 'warn', resolved: 'ok', closed: 'neutral' }

function StatCard({ label, tone, value, loading }) {
  return (
    <div className={`stat stat-${tone}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{loading && value === null ? <Loader size={18} /> : value ?? '—'}</span>
    </div>
  )
}

/** "12", or "200+" when the backend page limit was reached and the real number is higher. */
function formatCount(entry) {
  return entry ? `${entry.count}${entry.capped ? '+' : ''}` : null
}

export default function Tickets() {
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState(null)
  const { tickets, hasNext, loading, error, counts, statsLoading, statsError, refresh } = useTickets({ status, priority, page })

  const firstLoad = tickets === null
  const filtered = Boolean(status || priority)
  const term = search.trim().toLowerCase()
  const visible = (tickets ?? []).filter(
    (t) => !term || t.ticket_number.toLowerCase().includes(term) || t.title.toLowerCase().includes(term),
  )

  // The total is only shown when every per-status count is exact; otherwise it is a lower bound ("N+").
  const entries = counts ? Object.values(counts) : null
  const total = entries ? { count: entries.reduce((sum, e) => sum + e.count, 0), capped: entries.some((e) => e.capped) } : null

  function changeFilter(setter) {
    return (event) => {
      setter(event.target.value)
      setPage(0)
    }
  }

  return (
    <div className="tickets">
      <div className="kb-intro">
        <h2>Tickets</h2>
        <p>Track support tickets raised by voice or through the API. Open a ticket to read it and change its status or priority.</p>
      </div>

      <div className="stat-grid">
        <StatCard label="Total" tone="accent" value={formatCount(total)} loading={statsLoading} />
        {TICKET_STATUSES.map((s) => (
          <StatCard key={s} label={STATUS_LABELS[s]} tone={STAT_TONE[s]} value={formatCount(counts?.[s])} loading={statsLoading} />
        ))}
      </div>
      {statsError && (
        <p className="stat-note" role="alert">{statsError}</p>
      )}
      {entries?.some((e) => e.capped) && (
        <p className="stat-note">Counts are read in blocks of up to 200 tickets per status, so “200+” means at least 200.</p>
      )}

      <Card>
        <div className="card-head">
          <h2 className="card-title">All tickets</h2>
          <Button variant="secondary" className="btn-sm" onClick={refresh} disabled={loading}>
            {loading ? <Loader size={16} /> : <RefreshCw size={16} aria-hidden="true" />}
            Refresh
          </Button>
        </div>

        <div className="toolbar">
          <label className="field field-search">
            <span className="sr-only">Search tickets on this page</span>
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              placeholder="Search this page by number or title"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Status</span>
            <select value={status} onChange={changeFilter(setStatus)}>
              <option value="">All statuses</option>
              {TICKET_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Priority</span>
            <select value={priority} onChange={changeFilter(setPriority)}>
              <option value="">All priorities</option>
              {TICKET_PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p]}</option>)}
            </select>
          </label>
        </div>

        {firstLoad && loading && (
          <div className="library-state" role="status">
            <Loader size={22} />
            <p>Loading tickets…</p>
          </div>
        )}

        {firstLoad && !loading && error && (
          <div className="library-state" role="alert">
            <AlertTriangle size={26} aria-hidden="true" />
            <h3>Could not load tickets</h3>
            <p>{error}</p>
            <Button variant="secondary" className="btn-sm" onClick={refresh}>Try again</Button>
          </div>
        )}

        {!firstLoad && error && (
          <div className="banner banner-error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <span>{error} Showing the last list that loaded.</span>
          </div>
        )}

        {!firstLoad && tickets.length === 0 && (
          <div className="library-state">
            <Ticket size={28} aria-hidden="true" />
            <h3>{filtered || page > 0 ? 'No tickets match' : 'No tickets yet'}</h3>
            <p>
              {filtered || page > 0
                ? 'No tickets on this page match the selected filters. Try other filters or go back a page.'
                : 'Tickets created through the voice assistant or the API will appear here.'}
            </p>
          </div>
        )}

        {!firstLoad && tickets.length > 0 && visible.length === 0 && (
          <div className="library-state">
            <Search size={28} aria-hidden="true" />
            <h3>No search results</h3>
            <p>No ticket on this page matches “{search.trim()}”. Search covers only the tickets shown on this page.</p>
          </div>
        )}

        {!firstLoad && visible.length > 0 && (
          <div className={loading ? 'is-refreshing' : undefined} aria-busy={loading}>
            <TicketTable tickets={visible} onOpen={setOpenId} />
          </div>
        )}

        {!firstLoad && (page > 0 || hasNext) && (
          <div className="pager">
            <Button variant="secondary" className="btn-sm" icon={ChevronLeft} onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0 || loading}>
              Previous
            </Button>
            <span>Page {page + 1} · {PAGE_SIZE} per page</span>
            <Button variant="secondary" className="btn-sm" onClick={() => setPage((p) => p + 1)} disabled={!hasNext || loading}>
              Next
              <ChevronRight size={18} aria-hidden="true" />
            </Button>
          </div>
        )}
      </Card>

      {openId && <TicketDetails key={openId} ticketId={openId} onClose={() => setOpenId(null)} onUpdated={refresh} />}
    </div>
  )
}
