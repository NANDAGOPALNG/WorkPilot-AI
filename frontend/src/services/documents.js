import { api, getErrorMessage } from './api'
import { formatFileSize } from '../utils/format'

// Limits mirror the backend (backend/app/utils/file_validation.py). The backend stays the source of truth:
// it re-validates every upload, so these checks only save a pointless round trip.
export const SUPPORTED_EXTENSIONS = ['pdf', 'txt', 'docx']
export const SUPPORTED_LABEL = 'PDF, TXT, DOCX'
export const ACCEPT_ATTRIBUTE = SUPPORTED_EXTENSIONS.map((ext) => `.${ext}`).join(',')
export const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024 // 10 MB
export const MAX_FILE_SIZE_LABEL = '10 MB'

// The backend extracts, chunks and embeds the file before it answers, so a big document can take a while.
const UPLOAD_TIMEOUT_MS = 180000
// The backend allows up to 500 per request (default 100); ask for the maximum so the library is not silently cut short.
const LIST_LIMIT = 500

/** Returns a user-facing problem with the file, or null when it looks acceptable. */
export function validateFile(file) {
  const dot = file.name.lastIndexOf('.')
  const extension = dot > 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!SUPPORTED_EXTENSIONS.includes(extension)) return `Unsupported file type. Allowed: ${SUPPORTED_LABEL}.`
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `File too large (${formatFileSize(file.size)}). Maximum size is ${MAX_FILE_SIZE_LABEL}.`
  }
  return null
}

/**
 * Message safe to show in the UI. The backend's own messages are shown for client errors (4xx, e.g. "File too
 * large"); for server errors (5xx) they can contain provider details, so a generic message is used instead.
 */
export function documentErrorMessage(error, fallback) {
  const status = error?.response?.status
  if (typeof status === 'number' && status >= 500) return `${fallback} (HTTP ${status})`
  return getErrorMessage(error, fallback)
}

/** GET /api/documents -> array of { id, filename, file_type, file_size, status, created_at } */
export async function listDocuments() {
  const { data } = await api.get('/api/documents', { params: { limit: LIST_LIMIT } })
  if (!Array.isArray(data?.documents)) throw new Error('Unexpected response from the backend.')
  return data.documents.filter((doc) => doc && typeof doc.id === 'string')
}

/**
 * POST /api/documents/upload (multipart field "file") -> { id, filename, file_type, file_size, status, chunk_count, created_at }
 * onProgress receives 0..1 while the file is being sent; the server then still processes it before answering.
 */
export async function uploadDocument(file, { onProgress } = {}) {
  const form = new FormData()
  form.append('file', file, file.name)
  const { data } = await api.post('/api/documents/upload', form, {
    timeout: UPLOAD_TIMEOUT_MS,
    // The shared instance defaults to application/json, which would make axios JSON-encode the form. Asking for
    // multipart makes the browser add the boundary itself.
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event) => {
      const fraction = typeof event.progress === 'number' ? event.progress : event.total ? event.loaded / event.total : null
      if (fraction !== null) onProgress?.(Math.min(1, fraction))
    },
  })
  if (typeof data?.id !== 'string') throw new Error('Unexpected response from the backend.')
  return data
}

/** DELETE /api/documents/{id} -> { deleted: true, id }. Resolves only if the backend confirmed the deletion. */
export async function deleteDocument(documentId) {
  const { data } = await api.delete(`/api/documents/${encodeURIComponent(documentId)}`)
  if (data?.deleted !== true) throw new Error('The backend did not confirm the deletion.')
}
