import { API_BASE } from '../auth'

export function liveWsUrl() {
  if (API_BASE) return API_BASE.replace(/^http/i, 'ws') + '/live'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/live`
}
