import { useState } from 'react'
import { AlertTriangle, FileText, RefreshCw, Trash2 } from 'lucide-react'
import { deleteDocument, documentErrorMessage } from '../../services/documents'
import { formatDateTime, formatFileSize } from '../../utils/format'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Loader from '../ui/Loader'

// Only the statuses the backend actually uses; anything else is shown as-is in a neutral style.
const STATUS_VIEW = {
  ready: { tone: 'ok', label: 'Ready' },
  processing: { tone: 'pending', label: 'Processing' },
  failed: { tone: 'error', label: 'Failed' },
}

function StatusPill({ status }) {
  const view = STATUS_VIEW[status] ?? { tone: 'warn', label: status ? String(status) : 'Unknown' }
  return (
    <span className={`pill pill-${view.tone}`}>
      <i aria-hidden="true" />
      {view.label}
    </span>
  )
}

export default function DocumentList({ documents, loading, error, onRefresh }) {
  const [confirmId, setConfirmId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [deleteError, setDeleteError] = useState(null)
  const [notice, setNotice] = useState(null)
  const busyDeleting = deletingId !== null

  async function handleDelete(doc) {
    setDeletingId(doc.id)
    setDeleteError(null)
    setNotice(null)
    try {
      await deleteDocument(doc.id)
      setNotice(`"${doc.filename}" was deleted.`)
    } catch (err) {
      setDeleteError(documentErrorMessage(err, 'Could not delete the document. Please try again.'))
    } finally {
      setDeletingId(null)
      setConfirmId(null)
      onRefresh() // also after a failure, so the list reflects what the backend really has
    }
  }

  const firstLoad = documents === null
  const count = documents?.length ?? 0

  return (
    <Card>
      <div className="card-head">
        <h2 className="card-title">
          Document library{!firstLoad && <span className="card-count"> · {count}</span>}
        </h2>
        <Button variant="secondary" className="btn-sm" onClick={onRefresh} disabled={loading || busyDeleting}>
          {loading ? <Loader size={16} /> : <RefreshCw size={16} aria-hidden="true" />}
          Refresh
        </Button>
      </div>

      {deleteError && (
        <div className="banner banner-error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{deleteError}</span>
        </div>
      )}
      {notice && (
        <div className="banner banner-notice" role="status">
          <span>{notice}</span>
        </div>
      )}

      {firstLoad && loading && (
        <div className="library-state" role="status">
          <Loader size={22} />
          <p>Loading documents…</p>
        </div>
      )}

      {firstLoad && !loading && error && (
        <div className="library-state" role="alert">
          <AlertTriangle size={26} aria-hidden="true" />
          <h3>Could not load documents</h3>
          <p>{error}</p>
          <Button variant="secondary" className="btn-sm" onClick={onRefresh}>Try again</Button>
        </div>
      )}

      {!firstLoad && error && (
        <div className="banner banner-error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{error} Showing the last list that loaded.</span>
        </div>
      )}

      {!firstLoad && count === 0 && (
        <div className="library-state">
          <FileText size={28} aria-hidden="true" />
          <h3>No documents yet</h3>
          <p>Upload a PDF, TXT or DOCX file above and WorkPilot will be able to answer questions from it.</p>
        </div>
      )}

      {!firstLoad && count > 0 && (
        <div className="doc-table-wrap">
          <table className="doc-table">
            <caption className="sr-only">Uploaded documents</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Size</th>
                <th scope="col">Uploaded</th>
                <th scope="col">Status</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => {
                const deleting = deletingId === doc.id
                return (
                  <tr key={doc.id}>
                    <td className="doc-name">
                      <div className="doc-name-inner">
                        <FileText size={18} aria-hidden="true" />
                        <span title={doc.filename}>{doc.filename}</span>
                      </div>
                    </td>
                    <td data-label="Type">{doc.file_type ? String(doc.file_type).toUpperCase() : '—'}</td>
                    <td data-label="Size">{formatFileSize(doc.file_size)}</td>
                    <td data-label="Uploaded">{formatDateTime(doc.created_at)}</td>
                    <td data-label="Status"><StatusPill status={doc.status} /></td>
                    <td className="doc-actions">
                      {deleting ? (
                        <Button variant="danger" className="btn-sm" disabled>
                          <Loader size={16} />
                          Deleting…
                        </Button>
                      ) : confirmId === doc.id ? (
                        <div className="confirm" role="group" aria-label={`Confirm deleting ${doc.filename}`}>
                          <span>Delete this document and its indexed content?</span>
                          <Button variant="secondary" className="btn-sm" onClick={() => setConfirmId(null)} disabled={busyDeleting} autoFocus>
                            Cancel
                          </Button>
                          <Button variant="danger" className="btn-sm" onClick={() => handleDelete(doc)} disabled={busyDeleting}>
                            Delete
                          </Button>
                        </div>
                      ) : (
                        <Button
                          variant="danger"
                          className="btn-sm"
                          icon={Trash2}
                          onClick={() => setConfirmId(doc.id)}
                          disabled={busyDeleting}
                          aria-label={`Delete ${doc.filename}`}
                        >
                          Delete
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
