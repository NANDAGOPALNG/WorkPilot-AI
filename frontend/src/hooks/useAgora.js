import { useCallback, useEffect, useRef, useState } from 'react'
import { VoiceSession } from '../services/agora'

const STAGE_LABELS = {
  mic: 'Waiting for microphone permission…',
  session: 'Starting the voice agent…',
  joining: 'Joining the voice channel…',
  publishing: 'Starting your microphone…',
  live: 'Connected',
  ending: 'Ending the conversation…',
}

const INITIAL = {
  phase: 'idle', // idle | connecting | live | ending | error
  stage: null, // finer step while connecting (see STAGE_LABELS)
  error: null,
  notice: null,
  connectionState: 'DISCONNECTED', // Agora SDK connection state
  mic: 'off', // off | requesting | ready | live
  agent: 'none', // none | starting | joined | audio | left
  levels: { user: 0, agent: 0, userSpeaking: false, agentSpeaking: false },
  autoplayBlocked: false,
  sessionId: null,
}

/**
 * Voice conversation state for the Assistant screen. Everything shown comes from real events:
 * backend responses, Agora SDK events and measured audio levels.
 * The session is ended automatically when the component using this hook unmounts.
 */
export function useAgora() {
  const [state, setState] = useState(INITIAL)
  const sessionRef = useRef(null)
  const mountedRef = useRef(false)
  const endingRef = useRef(false)

  const patch = useCallback((changes) => {
    if (mountedRef.current) setState((prev) => ({ ...prev, ...changes }))
  }, [])

  // Mount/unmount. Written to survive React StrictMode's mount -> unmount -> mount in development:
  // the first cleanup finds no session and does nothing, and the flag is set again on the second mount.
  useEffect(() => {
    mountedRef.current = true
    const onPageHide = () => sessionRef.current?.stopOnUnload()
    window.addEventListener('pagehide', onPageHide)
    return () => {
      mountedRef.current = false
      window.removeEventListener('pagehide', onPageHide)
      const session = sessionRef.current
      sessionRef.current = null
      if (session) session.end() // releases mic, leaves the channel, stops the backend agent
    }
  }, [])

  const start = useCallback(async () => {
    if (sessionRef.current || endingRef.current) return // ignore repeated clicks: one session at a time

    const session = new VoiceSession({
      onStage: (stage) => patch({ stage, phase: stage === 'live' ? 'live' : 'connecting', sessionId: session.sessionId }),
      onConnectionState: (connectionState) => patch({ connectionState }),
      onMic: (mic) => patch({ mic }),
      onAgent: (agent) => patch({ agent }),
      onLevels: (levels) => patch({ levels }),
      onNotice: (notice) => patch({ notice }),
      onAutoplayBlocked: (autoplayBlocked) => patch({ autoplayBlocked }),
      onEnded: (message, { backendStopped }) => {
        if (sessionRef.current !== session) return
        sessionRef.current = null
        patch({ ...INITIAL, phase: 'error', error: message, notice: backendStopped ? null : unconfirmedStopNotice(session) })
      },
    })
    sessionRef.current = session
    patch({ ...INITIAL, phase: 'connecting', stage: 'mic' })

    try {
      await session.start()
    } catch (error) {
      if (sessionRef.current !== session) return // ended or unmounted in the meantime
      sessionRef.current = null
      patch({
        ...INITIAL,
        phase: 'error',
        error: error.message,
        notice: session.session && !session.backendStopped ? unconfirmedStopNotice(session) : null,
      })
    }
  }, [patch])

  const end = useCallback(async () => {
    const session = sessionRef.current
    if (!session || endingRef.current) return
    endingRef.current = true
    sessionRef.current = null
    patch({ phase: 'ending', stage: 'ending', notice: null, error: null })
    try {
      const { backendStopped } = await session.end()
      patch({ ...INITIAL, notice: backendStopped ? null : unconfirmedStopNotice(session) })
    } finally {
      endingRef.current = false
    }
  }, [patch])

  const resumeAudio = useCallback(() => sessionRef.current?.resumeAudio(), [])
  const dismissError = useCallback(() => patch({ error: null }), [patch])

  return {
    ...state,
    stageLabel: state.stage ? STAGE_LABELS[state.stage] : null,
    start,
    end,
    resumeAudio,
    dismissError,
  }
}

function unconfirmedStopNotice(session) {
  const idle = session.idleTimeoutSeconds
  return `The conversation ended, but the server did not confirm that the voice agent stopped.${
    idle ? ` It should leave by itself after about ${idle} seconds.` : ''
  }`
}
