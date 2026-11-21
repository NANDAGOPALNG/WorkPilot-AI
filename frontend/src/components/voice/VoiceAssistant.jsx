import { AlertTriangle, Mic, MicOff, PhoneOff, Volume2, X } from 'lucide-react'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Loader from '../ui/Loader'
import AgentStatus from './AgentStatus'
import VoiceWaveform from './VoiceWaveform'

/** What to show, derived only from real state. "Speaking" is claimed only from measured audio levels. */
function describe(v) {
  if (v.phase === 'ending') return { tone: 'busy', title: 'Ending…', text: 'Closing the microphone and stopping the voice agent.' }
  if (v.phase === 'connecting') return { tone: 'busy', title: v.stageLabel ?? 'Connecting…', text: 'This usually takes a few seconds.' }
  if (v.phase === 'error') return { tone: 'error', title: 'Something went wrong', text: 'You can start a new conversation when you are ready.' }
  if (v.phase === 'live') {
    if (v.agent === 'audio' && v.levels.agentSpeaking) return { tone: 'agent', title: 'Agent speaking', text: 'Speak any time to interrupt.' }
    if (v.levels.userSpeaking) return { tone: 'user', title: "You're speaking", text: 'Your microphone is picking up your voice.' }
    if (v.agent === 'audio') return { tone: 'live', title: 'Microphone live', text: 'Say something. The agent is connected.' }
    if (v.agent === 'joined') return { tone: 'live', title: 'Agent joined', text: 'Waiting for the agent to start its audio…' }
    return { tone: 'live', title: 'Waiting for the agent', text: 'You are connected. The agent has not joined the channel yet.' }
  }
  return { tone: 'idle', title: 'Ready when you are', text: 'Your browser will ask for microphone access when you start.' }
}

function OrbIcon({ tone, phase }) {
  if (phase === 'connecting' || phase === 'ending') return <Loader size={36} />
  if (phase === 'error') return <AlertTriangle size={36} aria-hidden="true" />
  if (tone === 'agent') return <Volume2 size={36} aria-hidden="true" />
  if (phase === 'live') return <Mic size={36} aria-hidden="true" />
  return <MicOff size={36} aria-hidden="true" />
}

export default function VoiceAssistant({ voice }) {
  const { phase, error, notice, levels, autoplayBlocked } = voice
  const view = describe(voice)
  const inCall = phase === 'connecting' || phase === 'live'
  const waveLevel = view.tone === 'agent' ? levels.agent : view.tone === 'user' ? levels.user : 0

  return (
    <div className="voice-grid">
      <Card className="stage">
        <div className={`orb orb-${view.tone}`} style={{ '--level': Math.min(1, waveLevel * 2.2) }}>
          <span className="orb-ring" aria-hidden="true" />
          <span className="orb-core">
            <OrbIcon tone={view.tone} phase={phase} />
          </span>
        </div>

        <div className="stage-text" role="status" aria-live="polite">
          <h3>{view.title}</h3>
          <p>{view.text}</p>
        </div>

        <VoiceWaveform level={waveLevel} active={phase === 'live' && (view.tone === 'agent' || view.tone === 'user')} />

        {error && (
          <div className="banner banner-error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <span>{error}</span>
            <button type="button" className="icon-btn" onClick={voice.dismissError} aria-label="Dismiss error">
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        )}
        {notice && (
          <div className="banner banner-notice" role="status">
            <span>{notice}</span>
          </div>
        )}
        {autoplayBlocked && (
          <Button variant="secondary" icon={Volume2} onClick={voice.resumeAudio}>
            Enable agent audio
          </Button>
        )}

        <div className="controls">
          {inCall || phase === 'ending' ? (
            <Button variant="danger" icon={PhoneOff} onClick={voice.end} disabled={phase === 'ending'}>
              {phase === 'connecting' ? 'Cancel' : 'End conversation'}
            </Button>
          ) : (
            <Button icon={Mic} onClick={voice.start}>
              {phase === 'error' ? 'Try again' : 'Start conversation'}
            </Button>
          )}
        </div>
      </Card>

      <div className="side">
        <Card title="Live status">
          <AgentStatus mic={voice.mic} agent={voice.agent} connectionState={voice.connectionState} sessionId={voice.sessionId} />
        </Card>
        <Card title="About this preview">
          <ul className="notes">
            <li>Voice only. Live transcription is not enabled.</li>
            <li>The agent is not connected to company documents or tickets yet, so it cannot look up policies or create tickets.</li>
            <li>Leaving this page or ending the conversation stops the agent.</li>
          </ul>
        </Card>
      </div>
    </div>
  )
}
