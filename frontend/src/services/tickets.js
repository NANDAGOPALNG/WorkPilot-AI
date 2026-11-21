import { api } from './api'

// Values mirror the backend (backend/app/schemas/ticket.py). The backend re-validates every request.
export const TICKET_STATUSES = ['open', 'in_progress', 'resolved', 'closed']
export const TICKET_PRIORITIES = ['low', 'medium', 'high', 'critical']

export const STATUS_LABELS = { open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' }
export const PRIORITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }

// The backend allows at most 200 tickets per request (GET /api/tickets?limit=...).
export const MAX_PAGE_LIMIT = 200

/**
 * GET /api/tickets -> array of { id, ticket_number, title, description, category, priority, status, created_at, updated_at }
 * Newest first. The backend's `count` is only the size of the returned page (not a total), so it is not used.
 */
export async function listTickets({ status, priority, limit = 50, offset = 0 } = {}) {
  const params = { limit, offset }
  if (status) params.status = status
  if (priority) params.priority = priority
  const { data } = await api.get('/api/tickets', { params })
  if (!Array.isArray(data?.tickets)) throw new Error('Unexpected response from the backend.')
  return data.tickets.filter((ticket) => ticket && typeof ticket.id === 'string')
}

/** GET /api/tickets/{id} -> one ticket. The id can be the ticket UUID or its number (TKT-1001). */
export async function getTicket(ticketId) {
  const { data } = await api.get(`/api/tickets/${encodeURIComponent(ticketId)}`)
  if (typeof data?.id !== 'string') throw new Error('Unexpected response from the backend.')
  return data
}

/**
 * PATCH /api/tickets/{id} with only status and/or priority -> the updated ticket.
 * Any other key is dropped here, so ids, ticket numbers and timestamps can never be sent from this screen.
 */
export async function updateTicket(ticketId, changes) {
  const body = {}
  if (changes.status !== undefined) {
    if (!TICKET_STATUSES.includes(changes.status)) throw new Error('Invalid status.')
    body.status = changes.status
  }
  if (changes.priority !== undefined) {
    if (!TICKET_PRIORITIES.includes(changes.priority)) throw new Error('Invalid priority.')
    body.priority = changes.priority
  }
  if (Object.keys(body).length === 0) throw new Error('Nothing to update.')
  const { data } = await api.patch(`/api/tickets/${encodeURIComponent(ticketId)}`, body)
  if (typeof data?.id !== 'string') throw new Error('Unexpected response from the backend.')
  return data
}

/**
 * Number of tickets with each status, from one filtered request per status (the backend has no totals endpoint).
 * A status that fills a whole request page is reported as capped: its real count is at least `count`.
 * -> { open: { count, capped }, ... }
 */
export async function loadStatusCounts() {
  const results = await Promise.all(
    TICKET_STATUSES.map((status) => listTickets({ status, limit: MAX_PAGE_LIMIT, offset: 0 })),
  )
  return Object.fromEntries(
    TICKET_STATUSES.map((status, i) => [status, { count: results[i].length, capped: results[i].length >= MAX_PAGE_LIMIT }]),
  )
}
