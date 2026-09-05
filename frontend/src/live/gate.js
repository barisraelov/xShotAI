/** LIVE-23: no frames / timer / analysis until GO. */

export function createLiveGate() {
  let phase = 'preview'
  return {
    get phase() { return phase },
    canSendFrames() { return phase === 'live' },
    canStartTimer() { return phase === 'live' },
    enterCountdown() { phase = 'countdown' },
    enterLive() { phase = 'live' },
    enterStopping() { phase = 'stopping' },
    reset() { phase = 'preview' },
  }
}
