// The Realtime API takes 24 kHz 16-bit mono PCM
const SAMPLE_RATE = 24000
// 50 ms frames keep the captions close behind your voice and the level meter moving smoothly
const FRAME = SAMPLE_RATE / 20

// On the audio thread: resamples the mic to 24 kHz (linear, between this block and the last
// sample of the one before) and posts 16-bit frames with their loudness for the meter
const CAPTURE = `
class Capture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.step = sampleRate / ${SAMPLE_RATE}
    this.at = 0
    this.last = 0
    this.frame = new Int16Array(${FRAME})
    this.n = 0
    this.energy = 0
  }
  process(inputs) {
    const input = inputs[0][0]
    if (!input) return true
    let at = this.at
    while (at < input.length - 1) {
      const i = Math.floor(at)
      const a = i < 0 ? this.last : input[i]
      const v = Math.max(-1, Math.min(1, a + (input[i + 1] - a) * (at - i)))
      this.energy += v * v
      this.frame[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff
      if (this.n === ${FRAME}) {
        const db = 10 * Math.log10(this.energy / ${FRAME} + 1e-10)
        this.port.postMessage({ pcm: this.frame.buffer, level: Math.max(0, Math.min(1, (db + 60) / 45)) }, [this.frame.buffer])
        this.frame = new Int16Array(${FRAME})
        this.n = 0
        this.energy = 0
      }
      at += this.step
    }
    this.at = at - input.length
    this.last = input[input.length - 1]
    return true
  }
}
registerProcessor('capture', Capture)
`

export interface ListenerEvents {
  /** How loud the mic is, 0 to 1, about 20 times a second. */
  level: (value: number) => void
  /** The words heard so far. */
  caption: (text: string) => void
  /** What was said, settled after you let go ("" when nothing was). */
  final: (text: string) => void
  error: (message: string) => void
}

/** The mic, heard while you talk: its audio streams to the backend, which relays it to OpenAI's
 *  live transcription, and the words come back as captions. */
export class Listener {
  private events: ListenerEvents
  private socket: WebSocket
  private queued: ArrayBuffer[] = []
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private stopping = false
  private done = false

  constructor(events: ListenerEvents) {
    this.events = events
    // Opened before the mic, so the transcription session comes up while the mic does
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    this.socket = new WebSocket(`${scheme}://${location.host}/api/agent/listen`)
    this.socket.binaryType = 'arraybuffer'
    this.socket.onopen = () => {
      for (const frame of this.queued) this.socket.send(frame)
      this.queued = []
      if (this.stopping) this.socket.send('stop')
    }
    this.socket.onmessage = (e: MessageEvent<string>) => {
      const message = JSON.parse(e.data) as { type: 'partial' | 'final' | 'error'; text?: string; detail?: string }
      if (message.type === 'partial') return this.events.caption(message.text ?? '')
      this.finish()
      if (message.type === 'final') this.events.final(message.text ?? '')
      else this.events.error(message.detail ?? "Couldn't hear that")
    }
    this.socket.onclose = () => {
      if (this.done) return
      this.finish()
      this.events.error("Couldn't hear that: the connection to the coach closed")
    }
  }

  /** Called from the press itself: browsers only let audio run when it starts from a gesture. */
  async start() {
    const module = URL.createObjectURL(new Blob([CAPTURE], { type: 'text/javascript' }))
    try {
      const context = this.context = new AudioContext()
      const [stream] = await Promise.all([
        navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }),
        context.audioWorklet.addModule(module),
      ])
      this.stream = stream
      if (this.stopping || this.done) return this.release()
      const capture = new AudioWorkletNode(context, 'capture')
      capture.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; level: number }>) => {
        this.events.level(e.data.level)
        if (this.socket.readyState === WebSocket.OPEN) this.socket.send(e.data.pcm)
        else this.queued.push(e.data.pcm)
      }
      context.createMediaStreamSource(this.stream).connect(capture)
      // Connected so the graph pulls it; it outputs silence
      capture.connect(context.destination)
    } catch (e) {
      // Let go while it was starting: that closed the audio, and "stop" brings the (empty) final
      if (this.stopping) return this.release()
      if (this.done) return
      this.cancel()
      this.events.error(e instanceof DOMException && e.name === 'NotAllowedError'
        ? 'The coach needs your microphone: allow it in the browser to talk.'
        : `The microphone didn't start: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      URL.revokeObjectURL(module)
    }
  }

  /** You let go: the mic closes, and what you said arrives settled as `final`. */
  stop() {
    if (this.stopping || this.done) return
    this.stopping = true
    this.release()
    if (this.socket.readyState === WebSocket.OPEN) this.socket.send('stop')
  }

  /** Drop it all, with no events. */
  cancel() {
    this.finish()
  }

  private finish() {
    this.done = true
    this.release()
    this.socket.close()
  }

  private release() {
    this.stream?.getTracks().forEach(t => t.stop())
    this.stream = null
    void this.context?.close()
    this.context = null
    this.events.level(0)
  }
}
