/** What of a reply is worth hearing: no tables, and no markdown marks read out. */
function speakable(text: string): string {
  return text
    .split('\n')
    .filter(line => !line.trim().startsWith('|'))
    .join(' ')
    .replace(/[*_`#>]+/g, '')
    .replace(/^\s*[-•]\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
}

// Short pieces are held back and joined, so speech comes in a few natural requests, not many
const MIN_PIECE = 60

/** Reads the coach's reply aloud while it is still being written: each finished sentence is
 *  turned into speech straight away and played in order, so it starts talking early. */
export class Speaker {
  private buffer = ''
  private piece = ''
  private chain: Promise<void> = Promise.resolve()
  private current: HTMLAudioElement | null = null
  private stopped = false
  private queued = 0
  private onSpeaking: (speaking: boolean) => void

  constructor(onSpeaking: (speaking: boolean) => void) {
    this.onSpeaking = onSpeaking
  }

  /** More of the reply, as it streams in. */
  feed(delta: string) {
    this.buffer += delta
    for (;;) {
      const end = /[.!?…](\s+)|\n+/.exec(this.buffer)
      if (!end) break
      const cut = end.index + end[0].length
      this.piece += this.buffer.slice(0, cut)
      this.buffer = this.buffer.slice(cut)
      if (speakable(this.piece).length >= MIN_PIECE) {
        this.say(this.piece)
        this.piece = ''
      }
    }
  }

  /** The reply is complete: say what's left. */
  flush() {
    this.say(this.piece + this.buffer)
    this.piece = ''
    this.buffer = ''
  }

  stop() {
    this.stopped = true
    this.current?.pause()
    this.onSpeaking(false)
  }

  private say(text: string) {
    const words = speakable(text)
    if (!words || this.stopped) return
    // Fetch now, play in turn: the next sentence is ready while this one plays
    const audio = fetch('/api/agent/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: words }),
    }).then(r => (r.ok ? r.blob() : null)).catch(() => null)
    this.queued += 1
    this.onSpeaking(true)
    this.chain = this.chain
      .then(async () => {
        const blob = await audio
        if (blob && !this.stopped) await this.play(blob)
      })
      .finally(() => {
        this.queued -= 1
        if (this.queued === 0) this.onSpeaking(false)
      })
  }

  private play(blob: Blob): Promise<void> {
    return new Promise(resolve => {
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      this.current = audio
      const done = () => { URL.revokeObjectURL(url); resolve() }
      audio.onended = done
      audio.onerror = done
      audio.onpause = done
      audio.play().catch(done)
    })
  }
}
