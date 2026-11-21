import VoiceAssistant from '../components/voice/VoiceAssistant'
import { useAgora } from '../hooks/useAgora'

export default function Assistant() {
  // The hook lives here on purpose: leaving this screen unmounts it, which ends the conversation.
  const voice = useAgora()
  return (
    <div className="assistant">
      <div className="assistant-intro">
        <h2>Hi, I'm WorkPilot.</h2>
        <p>Start a conversation and talk to me out loud. I'll answer by voice.</p>
      </div>
      <VoiceAssistant voice={voice} />
    </div>
  )
}
