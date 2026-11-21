import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, FileText, Upload, X } from 'lucide-react'
import {
  ACCEPT_ATTRIBUTE,
  MAX_FILE_SIZE_LABEL,
  SUPPORTED_LABEL,
  documentErrorMessage,
  uploadDocument,
  validateFile,
} from '../../services/documents'
import { formatFileSize } from '../../utils/format'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Loader from '../ui/Loader'

const ACTIVE = ['queued', 'uploading', 'processing']
const signature = (file) => `${file.name}|${file.size}|${file.lastModified}`

function RowIcon({ status }) {
  if (status === 'done') return <Check size={18} aria-hidden="true" />
  if (status === 'error') return <AlertTriangle size={18} aria-hidden="true" />
  if (status === 'uploading' || status === 'processing') return <Loader size={18} />
  return <FileText size={18} aria-hidden="true" />
}

function UploadRow({ item, onDismiss }) {
  const percent = Math.round(item.progress * 100)
  const finished = !ACTIVE.includes(item.status)
  return (
    <li className={`upload-row is-${item.status}`}>
      <span className="upload-icon">
        <RowIcon status={item.status} />
      </span>
      <div className="upload-body">
        <div className="upload-top">
          <span className="upload-name" title={item.name}>{item.name}</span>
          <span className="upload-size">{formatFileSize(item.size)}</span>
        </div>
        {item.status === 'queued' && <p className="upload-note">Waiting for the previous upload to finish…</p>}
        {item.status === 'uploading' && (
          <>
            <div className="progress" role="progressbar" aria-label={`Uploading ${item.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
              <span style={{ width: `${percent}%` }} />
            </div>
            <p className="upload-note">Uploading… {percent}%</p>
          </>
        )}
        {item.status === 'processing' && (
          <>
            <div className="progress is-indeterminate" role="progressbar" aria-label={`Processing ${item.name}`}>
              <span />
            </div>
            <p className="upload-note">Processing and indexing. This can take a moment for larger files.</p>
          </>
        )}
        {item.status === 'done' && (
          <p className="upload-note upload-ok">
            {item.resultStatus === 'ready' ? 'Added to the knowledge base.' : `Uploaded (status: ${item.resultStatus ?? 'unknown'}).`}
          </p>
        )}
        {item.status === 'error' && <p className="upload-note upload-fail">{item.error}</p>}
      </div>
      {finished && (
        <button type="button" className="icon-btn" onClick={() => onDismiss(item.id)} aria-label={`Dismiss ${item.name}`}>
          <X size={16} aria-hidden="true" />
        </button>
      )}
    </li>
  )
}

export default function DocumentUpload({ onUploadFinished }) {
  const [items, setItems] = useState([])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)
  const pendingRef = useRef([]) // files waiting for their turn (File objects stay out of React state)
  const runningRef = useRef(false) // true while the queue loop is active: only one upload at a time
  const activeRef = useRef(new Set()) // signatures queued/uploading: the same file cannot be submitted twice at once
  const aliveRef = useRef(true)
  const idRef = useRef(0)
  const onFinishedRef = useRef(onUploadFinished)

  useEffect(() => {
    onFinishedRef.current = onUploadFinished
  })

  useEffect(() => {
    aliveRef.current = true
    return () => {
      // Leaving the page: files that have not started are dropped; one already in flight still completes on the server.
      aliveRef.current = false
      pendingRef.current = []
    }
  }, [])

  const patch = useCallback((id, changes, onlyWhile) => {
    setItems((list) => list.map((item) => (item.id === id && (!onlyWhile || item.status === onlyWhile) ? { ...item, ...changes } : item)))
  }, [])

  const runQueue = useCallback(async () => {
    if (runningRef.current) return
    runningRef.current = true
    try {
      while (aliveRef.current && pendingRef.current.length) {
        const next = pendingRef.current.shift()
        patch(next.id, { status: 'uploading', progress: 0 })
        try {
          const result = await uploadDocument(next.file, {
            // Once every byte is sent the server still extracts and embeds the file, which is the slow part.
            onProgress: (fraction) => patch(next.id, fraction >= 1 ? { status: 'processing', progress: 1 } : { progress: fraction }, 'uploading'),
          })
          patch(next.id, { status: 'done', progress: 1, resultStatus: result.status })
        } catch (error) {
          patch(next.id, { status: 'error', error: documentErrorMessage(error, 'The server could not process this file. Please try again later.') })
        } finally {
          activeRef.current.delete(next.sig)
          onFinishedRef.current?.() // also after a failure: the backend may have recorded the document as failed
        }
      }
    } finally {
      runningRef.current = false
    }
  }, [patch])

  const addFiles = useCallback(
    (fileList) => {
      const added = []
      for (const file of Array.from(fileList ?? [])) {
        const sig = signature(file)
        if (activeRef.current.has(sig)) continue // already queued or uploading: ignore the duplicate submit
        const id = ++idRef.current
        const base = { id, name: file.name, size: file.size, progress: 0, error: null, resultStatus: null }
        const problem = validateFile(file)
        if (problem) {
          added.push({ ...base, status: 'error', error: problem }) // never sent to the backend
          continue
        }
        activeRef.current.add(sig)
        pendingRef.current.push({ id, file, sig })
        added.push({ ...base, status: 'queued' })
      }
      if (!added.length) return
      setItems((list) => [...list, ...added])
      runQueue()
    },
    [runQueue],
  )

  function handleDrop(event) {
    event.preventDefault()
    setDragging(false)
    addFiles(event.dataTransfer.files)
  }

  function handleBrowse(event) {
    addFiles(event.target.files)
    event.target.value = '' // lets the same file be picked again later
  }

  const dismiss = (id) => setItems((list) => list.filter((item) => item.id !== id))
  const clearFinished = () => setItems((list) => list.filter((item) => ACTIVE.includes(item.status)))
  const hasFinished = items.some((item) => !ACTIVE.includes(item.status))

  return (
    <Card>
      <h2 className="card-title">Upload documents</h2>
      <div
        className={`dropzone${dragging ? ' is-dragging' : ''}`}
        onDragEnter={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false)
        }}
        onDrop={handleDrop}
      >
        <Upload className="dropzone-icon" size={28} aria-hidden="true" />
        <h3>{dragging ? 'Drop to upload' : 'Drag and drop files here'}</h3>
        <p>or</p>
        <Button onClick={() => inputRef.current?.click()}>Browse files</Button>
        <input ref={inputRef} type="file" multiple accept={ACCEPT_ATTRIBUTE} onChange={handleBrowse} hidden />
        <p className="dropzone-hint">
          Supported: {SUPPORTED_LABEL} · up to {MAX_FILE_SIZE_LABEL} per file. Files upload one at a time.
        </p>
      </div>

      {items.length > 0 && (
        <>
          <ul className="upload-list" aria-live="polite">
            {items.map((item) => (
              <UploadRow key={item.id} item={item} onDismiss={dismiss} />
            ))}
          </ul>
          {hasFinished && (
            <div className="upload-actions">
              <Button variant="secondary" className="btn-sm" onClick={clearFinished}>
                Clear finished
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  )
}
