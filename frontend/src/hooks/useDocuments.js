import { useCallback, useEffect, useState } from 'react'
import { documentErrorMessage, listDocuments } from '../services/documents'

/**
 * Loads the document library from the backend.
 * `documents` is null until the first successful load; later refreshes keep showing the previous list.
 */
export function useDocuments() {
  const [documents, setDocuments] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let cancelled = false // a newer refresh (or unmount) makes this answer stale
    listDocuments()
      .then((docs) => {
        if (cancelled) return
        setDocuments(docs)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(documentErrorMessage(err, 'Could not load documents.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [version])

  const refresh = useCallback(() => {
    setLoading(true)
    setVersion((v) => v + 1)
  }, [])

  return { documents, loading, error, refresh }
}
