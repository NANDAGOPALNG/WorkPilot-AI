import AgoraRTC from 'agora-rtc-sdk-ng'
import { api, API_BASE_URL, getErrorMessage } from './api'

AgoraRTC.setLogLevel(2) // SDK logs: warnings and errors only

// ---------------------------------------------------------------------------------------------
// Backend session API (POST /api/agora/sessions, POST /api/agora/sessions/{id}/stop)
// ---------------------------------------------------------------------------------------------
const START_FIELDS = {
  session_id: 'string',
  status: 'string',
  app_id: 'string',
  channel: 'string',
  user_uid: 'number',
  agent_uid: 'number',
  rtc_token: 'string',
  token_expires_in_seconds: 'number',
  idle_timeout_seconds: 'number',
}

export class VoiceError extends Error {
  constructor(message, kind = 'unknown') {
    super(message)
    this.name = 'VoiceError'
    this.kind = kind // 'mic' | 'backend' | 'rtc' | 'unknown'
  }
}

class AbortedError extends Error {}

/** Start a voice agent. Validates the response against the backend's StartSessionResponse schema. */
export async function startSession() {
  let data
  try {
    ;({ data } = await api.post('/api/agora/sessions'))
  } catch (error) {
    throw new VoiceError(getErrorMessage(error, 'Could not start the voice session.'), 'backend')
  }
  const bad = Object.entries(START_FIELDS).filter(([key, type]) => typeof data?.[key] !== type).map(([key]) => key)
  if (bad.length) {
    throw new VoiceError(`Unexpected response from the backend (invalid fields: ${bad.join(', ')}).`, 'backend')
  }
  return data
}

/** Stop a voice agent. Resolves only if the backend confirmed the stop. */
export async function stopSession(sessionId) {
  const { data } = await api.post(`/api/agora/sessions/${encodeURIComponent(sessionId)}/stop`, null, { timeout: 15000 })
  if (data?.status !== 'stopped') throw new Error('Backend did not confirm the stop.')
}

// Best-effort stop while the page is closing (fetch keepalive survives unload; the response is not awaited).
function stopSessionOnUnload(sessionId) {
  try {
    fetch(`${API_BASE_URL}/api/agora/sessions/${encodeURIComponent(sessionId)}/stop`, { method: 'POST', keepalive: true }).catch(() => {})
  } catch {
    /* nothing else can be done while unloading */
  }
}

// ---------------------------------------------------------------------------------------------
// RTC voice session
// ---------------------------------------------------------------------------------------------
const LEVEL_POLL_MS = 100
const USER_SPEAKING_LEVEL = 0.06 // Agora volume levels are 0..1
const AGENT_SPEAKING_LEVEL = 0.04
const SPEAKING_HOLD_MS = 350 // keep the "speaking" flag briefly so it does not flicker between words
const AGENT_WAIT_NOTICE_MS = 20000

function describeMicError(error) {
  const code = error?.code
  const name = error?.name
  if (code === 'PERMISSION_DENIED' || name === 'NotAllowedError') {
    return 'Microphone access was denied. Allow the microphone for this site in your browser settings, then try again.'
  }
  if (code === 'DEVICE_NOT_FOUND' || name === 'NotFoundError') return 'No microphone was found. Connect one and try again.'
  if (code === 'NOT_READABLE' || name === 'NotReadableError') return 'The microphone is being used by another application.'
  return `Could not start the microphone${code ? ` (${code})` : ''}.`
}

/**
 * One voice conversation: microphone -> backend session -> RTC join/publish -> remote agent audio.
 * Create one per conversation. All UI updates go through `handlers`; the class never touches React.
 *
 * handlers: onStage(stage), onConnectionState(state), onMic(state), onAgent(state), onLevels(levels),
 *           onNotice(text|null), onAutoplayBlocked(bool), onEnded(message, { backendStopped })
 */
export class VoiceSession {
  constructor(handlers) {
    this.h = handlers
    this.client = null
    this.mic = null
    this.micPublished = false
    this.agentTrack = null
    this.session = null // backend StartSessionResponse
    this.backendStopped = false
    this.closing = false
    this.live = false
    this.agentState = 'none' // none | starting | joined | audio | left
    this.pollTimer = null
    this.waitTimer = null
    this.lastAgentVoice = 0
    this.lastUserVoice = 0
    this.lastLevels = null
    this.tearingDown = Promise.resolve()
    this.onAutoplayFailed = () => {
      if (!this.closing) this.h.onAutoplayBlocked(true)
    }
  }

  get sessionId() {
    return this.session?.session_id ?? null
  }

  get idleTimeoutSeconds() {
    return this.session?.idle_timeout_seconds ?? null
  }

  // ------------------------------------------------------------------ start
  async start() {
    try {
      // 1. Microphone first (still inside the user's click), so a denied permission never starts a paid agent.
      this.h.onStage('mic')
      this.h.onMic('requesting')
      this.mic = await this._createMicrophone()
      this._assertOpen()
      this.h.onMic('ready')

      // 2. Backend creates the channel and starts the agent.
      this.h.onStage('session')
      const session = await startSession()
      this.session = session
      this._assertOpen() // if the user cancelled meanwhile, the catch below stops the agent we just started
      this._setAgent('starting')

      // 3. Join the RTC channel with the values the backend returned.
      this.h.onStage('joining')
      this.client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' }) // "rtc" = free-for-all call; codec only matters for video
      this._attachListeners()
      AgoraRTC.on('autoplay-failed', this.onAutoplayFailed)
      try {
        await this.client.join(session.app_id, session.channel, session.rtc_token, session.user_uid)
      } catch (error) {
        if (this.closing) throw new AbortedError()
        throw new VoiceError(`Could not join the voice channel${error?.code ? ` (${error.code})` : ''}.`, 'rtc')
      }
      this._assertOpen()

      // 4. Publish the microphone.
      this.h.onStage('publishing')
      try {
        await this.client.publish(this.mic)
      } catch (error) {
        if (this.closing) throw new AbortedError()
        throw new VoiceError(`Could not publish the microphone${error?.code ? ` (${error.code})` : ''}.`, 'rtc')
      }
      this.micPublished = true
      this._assertOpen()

      this.live = true
      this.h.onMic('live')
      this.h.onStage('live')
      this._startPolling()
      this.waitTimer = setTimeout(() => {
        if (!this.closing && this.agentState !== 'audio') {
          this.h.onNotice("The agent hasn't started talking yet. It may still be starting; if this persists, check the backend logs.")
        }
      }, AGENT_WAIT_NOTICE_MS)
    } catch (error) {
      const aborted = error instanceof AbortedError
      await this.teardown() // always release the mic, leave the channel and stop the agent
      if (aborted) return
      throw error instanceof VoiceError ? error : new VoiceError(error?.message || 'Could not start the conversation.', 'unknown')
    }
  }

  async _createMicrophone() {
    try {
      return await AgoraRTC.createMicrophoneAudioTrack()
    } catch (error) {
      if (this.closing) throw new AbortedError()
      throw new VoiceError(describeMicError(error), 'mic')
    }
  }

  _assertOpen() {
    if (this.closing) throw new AbortedError()
  }

  // ------------------------------------------------------------------ RTC events
  _isAgent(user) {
    return this.session != null && String(user.uid) === String(this.session.agent_uid)
  }

  _setAgent(state) {
    this.agentState = state
    this.h.onAgent(state)
  }

  _attachListeners() {
    const c = this.client

    c.on('connection-state-change', (current, _previous, reason) => {
      if (this.closing) return
      this.h.onConnectionState(current)
      if (current === 'DISCONNECTED' && this.live) this._fail(`The voice connection was lost${reason ? ` (${reason})` : ''}.`)
    })

    c.on('user-joined', (user) => {
      if (!this.closing && this._isAgent(user) && this.agentState !== 'audio') this._setAgent('joined')
    })

    // The agent may join and publish well after we do; the SDK also replays this event for users already publishing.
    c.on('user-published', async (user, mediaType) => {
      if (this.closing || mediaType !== 'audio' || !this._isAgent(user)) return
      try {
        const track = await c.subscribe(user, 'audio')
        if (this.closing) return
        this.agentTrack = track
        track.play() // SDK playback; may be blocked by autoplay policy -> 'autoplay-failed'
        clearTimeout(this.waitTimer)
        this.h.onNotice(null)
        this._setAgent('audio')
      } catch (error) {
        if (!this.closing) this.h.onNotice(`Could not play the agent's audio${error?.code ? ` (${error.code})` : ''}.`)
      }
    })

    c.on('user-unpublished', (user, mediaType) => {
      if (this.closing || mediaType !== 'audio' || !this._isAgent(user)) return
      this.agentTrack = null
      this._setAgent('joined')
    })

    c.on('user-left', (user) => {
      if (!this.closing && this._isAgent(user)) {
        this._setAgent('left')
        this._fail('The voice agent left the conversation.')
      }
    })

    // The backend has no token-renewal endpoint yet, so the honest options are to warn and then end.
    c.on('token-privilege-will-expire', () => {
      if (!this.closing) this.h.onNotice('This session expires in about 30 seconds. End it and start a new conversation to continue.')
    })
    c.on('token-privilege-did-expire', () => {
      if (!this.closing) this._fail('The session expired. Start a new conversation.')
    })

    // Quality warnings (low bitrate etc.). Not fatal; logged for debugging only.
    c.on('exception', (event) => console.warn('[agora] exception', event?.code, event?.msg))
  }

  async _fail(message) {
    if (this.closing) return
    await this.teardown()
    this.h.onEnded(message, { backendStopped: this.backendStopped })
  }

  // ------------------------------------------------------------------ levels
  _startPolling() {
    this.pollTimer = setInterval(() => {
      const now = Date.now()
      const user = this.mic?.getVolumeLevel() ?? 0
      const agent = this.agentTrack?.getVolumeLevel() ?? 0
      if (user > USER_SPEAKING_LEVEL) this.lastUserVoice = now
      if (agent > AGENT_SPEAKING_LEVEL) this.lastAgentVoice = now
      const levels = {
        user: Math.round(user * 20) / 20,
        agent: Math.round(agent * 20) / 20,
        userSpeaking: now - this.lastUserVoice < SPEAKING_HOLD_MS,
        agentSpeaking: now - this.lastAgentVoice < SPEAKING_HOLD_MS,
      }
      const last = this.lastLevels
      if (!last || Object.keys(levels).some((k) => levels[k] !== last[k])) {
        this.lastLevels = levels
        this.h.onLevels(levels)
      }
    }, LEVEL_POLL_MS)
  }

  /** Call from a click handler if the browser blocked automatic playback. */
  resumeAudio() {
    try {
      this.agentTrack?.play()
      this.h.onAutoplayBlocked(false)
    } catch (error) {
      console.warn('[agora] could not resume audio', error?.code)
    }
  }

  // ------------------------------------------------------------------ end / cleanup
  /** End the conversation. Safe to call repeatedly. Resolves with whether the backend confirmed the stop. */
  async end() {
    await this.teardown()
    return { backendStopped: this.backendStopped || !this.session }
  }

  teardown() {
    // Runs are serialized, so a late `start()` continuation cannot race an earlier teardown.
    this.tearingDown = this.tearingDown.then(() => this._teardown())
    return this.tearingDown
  }

  async _teardown() {
    this.closing = true
    this.live = false
    clearInterval(this.pollTimer)
    clearTimeout(this.waitTimer)
    this.pollTimer = this.waitTimer = null
    AgoraRTC.off('autoplay-failed', this.onAutoplayFailed)

    const { client, mic, agentTrack } = this
    this.client = this.mic = this.agentTrack = null

    try {
      agentTrack?.stop() // stop remote playback
    } catch {
      /* already stopped */
    }
    if (client) client.removeAllListeners()
    if (mic) {
      try {
        if (client && this.micPublished) await client.unpublish(mic)
      } catch (error) {
        console.warn('[agora] unpublish failed', error?.code)
      }
      this.micPublished = false
      try {
        mic.stop()
        mic.close() // releases the microphone (the browser's recording indicator goes off)
      } catch (error) {
        console.warn('[agora] closing the microphone failed', error?.code)
      }
    }
    if (client) {
      try {
        await client.leave()
      } catch (error) {
        console.warn('[agora] leave failed', error?.code)
      }
    }
    await this._stopBackendAgent()
  }

  async _stopBackendAgent() {
    if (!this.session || this.backendStopped) return
    try {
      await stopSession(this.session.session_id)
      this.backendStopped = true
    } catch (error) {
      // Stays false so a later call can retry. Message only: never log request details.
      console.warn('[agora] backend stop failed:', getErrorMessage(error))
    }
  }

  /** For `pagehide`: fire-and-forget stop, because async teardown cannot finish while the page unloads. */
  stopOnUnload() {
    if (this.session && !this.backendStopped) stopSessionOnUnload(this.session.session_id)
  }
}
