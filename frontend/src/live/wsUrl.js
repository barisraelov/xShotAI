import { getLiveRuntimeConfig, livePageWsUrl } from './liveConfig'

export function liveWsUrl() {
  const cfg = getLiveRuntimeConfig()
  if (!cfg.ok || cfg.blocked) {
    throw new Error(cfg.message || 'Live is not configured')
  }
  if (cfg.wsUrl) return cfg.wsUrl
  return livePageWsUrl()
}

export function liveConfigBlocked() {
  const cfg = getLiveRuntimeConfig()
  return cfg.blocked ? cfg : null
}
