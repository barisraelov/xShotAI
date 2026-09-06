export const PROTOCOL_VERSION = 1
export const JPEG_QUALITY = 0.8

export function packFrame(header, jpegBytes) {
  const enc = new TextEncoder()
  const headerJson = enc.encode(JSON.stringify(header))
  const out = new Uint8Array(6 + headerJson.length + jpegBytes.byteLength)
  out[0] = 88
  out[1] = 83
  out[2] = 72
  out[3] = 49
  out[4] = (headerJson.length >> 8) & 255
  out[5] = headerJson.length & 255
  out.set(headerJson, 6)
  out.set(jpegBytes, 6 + headerJson.length)
  return out
}

export function frameHeader({ liveSessionId, frameId, captureTs, width, height, jpegQuality = JPEG_QUALITY, bufferedAmount }) {
  const header = {
    protocol_version: PROTOCOL_VERSION,
    live_session_id: liveSessionId,
    frame_id: frameId,
    capture_timestamp_monotonic_ms: captureTs,
    width,
    height,
    jpeg_quality: jpegQuality,
  }
  if (bufferedAmount != null) header.client_buffered_amount = bufferedAmount
  return header
}
