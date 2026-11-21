const MIC = {
  off: ['Off', 'idle'],
  requesting: ['Waiting for permission', 'pending'],
  ready: ['Captured, not yet sent', 'pending'],
  live: ['Live', 'ok'],
}
const AGENT = {
  none: ['Not started', 'idle'],
  starting: ['Starting, not in channel yet', 'pending'],
  joined: ['In channel, no audio yet', 'pending'],
  audio: ['Audio connected', 'ok'],
  left: ['Left the channel', 'error'],
}
const CONNECTION = {
  DISCONNECTED: ['Not connected', 'idle'],
  CONNECTING: ['Connecting', 'pending'],
  RECONNECTING: ['Reconnecting', 'warn'],
  CONNECTED: ['Connected', 'ok'],
  DISCONNECTING: ['Disconnecting', 'pending'],
}

function Row({ label, value: [text, tone] }) {
  return (
    <li className="status-row">
      <span className="status-label">{label}</span>
      <span className={`pill pill-${tone}`}>
        <i aria-hidden="true" />
        {text}
      </span>
    </li>
  )
}

export default function AgentStatus({ mic, agent, connectionState, sessionId }) {
  return (
    <>
      <ul className="status-list" aria-label="Connection status">
        <Row label="Connection" value={CONNECTION[connectionState] ?? [connectionState, 'idle']} />
        <Row label="Microphone" value={MIC[mic] ?? ['Unknown', 'idle']} />
        <Row label="Agent" value={AGENT[agent] ?? ['Unknown', 'idle']} />
      </ul>
      {sessionId && <p className="session-id">Session {sessionId.length > 12 ? `${sessionId.slice(0, 6)}…${sessionId.slice(-4)}` : sessionId}</p>}
    </>
  )
}
