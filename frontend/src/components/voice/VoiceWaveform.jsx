const BARS = 9

/** Bars driven by a real 0..1 audio level. Flat (and still) when `active` is false. */
export default function VoiceWaveform({ level = 0, active = false }) {
  return (
    <div className={`waveform ${active ? 'is-active' : ''}`} aria-hidden="true">
      {Array.from({ length: BARS }, (_, i) => {
        const shape = 1 - Math.abs(i - (BARS - 1) / 2) / (BARS / 2) // taller in the middle
        const height = active ? 8 + Math.min(1, level * 2.2) * 40 * shape : 6
        return <span key={i} style={{ height }} />
      })}
    </div>
  )
}
