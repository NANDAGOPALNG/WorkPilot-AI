import { useCallback, useEffect, useState } from 'react'
import { getErrorMessage } from '../services/api'
import { listTickets, loadStatusCounts } from '../services/tickets'

export const PAGE_SIZE = 20

/**
 * Loads one page of tickets (server-side status/priority filters, limit/offset paging) plus per-status counts.
 * `tickets` is null until the first successful load; later loads keep showing the previous rows meanwhile.
 * Loading is derived (the request key differs from the last settled key), so no state is set inside effects.
 */
export function useTickets({ status, priority, page }) {
  const [version, setVersion] = useState(0)
  const listKey = `${status}|${priority}|${page}|${version}`
  const [list, setList] = useState({ tickets: null, hasNext: false, error: null, settledKey: null })
  const [stats, setStats] = useState({ counts: null, error: null, settledKey: null })

  useEffect(() => {
    let cancelled = false // a newer request (or unmount) makes this answer stale
    // Ask for one extra row: if it comes back there is a next page, and no separate total is needed.
    listTickets({ status: status || undefined, priority: priority || undefined, limit: PAGE_SIZE + 1, offset: page * PAGE_SIZE })
      .then((rows) => {
        if (cancelled) return
        setList({ tickets: rows.slice(0, PAGE_SIZE), hasNext: rows.length > PAGE_SIZE, error: null, settledKey: listKey })
      })
      .catch((err) => {
        if (!cancelled) setList((prev) => ({ ...prev, error: getErrorMessage(err, 'Could not load tickets.'), settledKey: listKey }))
      })
    return () => {
      cancelled = true
    }
  }, [status, priority, page, version, listKey])

  useEffect(() => {
    let cancelled = false
    loadStatusCounts()
      .then((counts) => {
        if (!cancelled) setStats({ counts, error: null, settledKey: version })
      })
      .catch((err) => {
        if (!cancelled) setStats((prev) => ({ ...prev, error: getErrorMessage(err, 'Could not load ticket counts.'), settledKey: version }))
      })
    return () => {
      cancelled = true
    }
  }, [version])

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  return {
    tickets: list.tickets,
    hasNext: list.hasNext,
    loading: list.settledKey !== listKey,
    error: list.error,
    counts: stats.counts,
    statsLoading: stats.settledKey !== version,
    statsError: stats.error,
    refresh,
  }
}
