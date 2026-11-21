import axios from 'axios'

// Backend base URL. Configure with VITE_API_BASE_URL (see .env.example); no deployment URL is hardcoded.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000, // starting a voice agent calls Agora from the backend, so allow for a slow answer
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Turn an axios error into a message that is safe and useful to show in the UI.
 * The backend reports errors as { detail: { message } }; FastAPI validation errors use { detail: [...] }.
 */
export function getErrorMessage(error, fallback = 'Something went wrong.') {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail?.message === 'string' && detail.message) return detail.message
    if (error.response) {
      return error.response.status === 422 ? 'The request was rejected as invalid.' : `${fallback} (HTTP ${error.response.status})`
    }
    if (error.code === 'ECONNABORTED') return 'The backend took too long to respond.'
    return `Cannot reach the WorkPilot backend at ${API_BASE_URL}. Is it running?`
  }
  return error?.message || fallback
}
