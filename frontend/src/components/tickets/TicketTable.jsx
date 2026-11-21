import { formatDateTime } from '../../utils/format'
import { PriorityBadge, StatusBadge } from './TicketBadges'

export default function TicketTable({ tickets, onOpen }) {
  return (
    <div className="ticket-table-wrap">
      <table className="ticket-table">
        <caption className="sr-only">Support tickets</caption>
        <thead>
          <tr>
            <th scope="col">Ticket</th>
            <th scope="col">Title</th>
            <th scope="col">Category</th>
            <th scope="col">Priority</th>
            <th scope="col">Status</th>
            <th scope="col">Created</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => (
            <tr key={ticket.id} className="ticket-row" onClick={() => onOpen(ticket.id)}>
              <td className="ticket-number">
                {/* The button keeps the row reachable and operable by keyboard; clicking anywhere on the row works too. */}
                <button
                  type="button"
                  className="link-btn"
                  onClick={(event) => {
                    event.stopPropagation()
                    onOpen(ticket.id)
                  }}
                  aria-label={`Open ticket ${ticket.ticket_number}`}
                >
                  {ticket.ticket_number}
                </button>
              </td>
              <td className="ticket-title"><span title={ticket.title}>{ticket.title}</span></td>
              <td data-label="Category" className="ticket-category">{ticket.category || '—'}</td>
              <td data-label="Priority"><PriorityBadge priority={ticket.priority} /></td>
              <td data-label="Status"><StatusBadge status={ticket.status} /></td>
              <td data-label="Created">{formatDateTime(ticket.created_at)}</td>
              <td data-label="Updated">{formatDateTime(ticket.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
