/** Live API / WebSocket configuration (FIX-05 / PATCH-04 / LIVE-25). */

export const PRODUCTION_API_HOSTS = ['xshotai.up.railway.app']
export const PRODUCTION_API_ORIGIN = 'https://xshotai.up.railway.app'

export const LIVE_CONFIG_MESSAGES = {
  missing_vite_api_url:
    'Live is not configured: missing VITE_API_URL. Preview must point at Staging, never Production.',
  production_api_blocked:
    'Live is blocked: the Production API is not allowed. Set VITE_API_URL to Staging, or opt in on Vercel Production with VITE_ENABLE_LIVE_PRODUCTION=true.',
  preview_points_at_production:
    'Live is blocked: this Preview build points at the Production API. Use the Staging URL.',
}

export function isLocalDevHost(host) {
  const h = String(host || '').toLowerCase()
  return h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]'
}

export function hostnameOf(url) {
  if (!url) return ''
  try {
    return new URL(url).hostname.toLowerCase()
  } catch {
    return ''
  }
}

export function isProductionApiUrl(url) {
  if (!url) return false
  const host = hostnameOf(url)
  if (host && PRODUCTION_API_HOSTS.includes(host)) return true
  const lower = String(url).toLowerCase()
  return PRODUCTION_API_HOSTS.some(h => lower.includes(h))
}

export function isLiveProductionOptIn(value) {
  return String(value ?? '').trim().toLowerCase() === 'true'
}

export function isExactProductionApiUrl(url) {
  return String(url || '').trim().replace(/\/$/, '').toLowerCase() === PRODUCTION_API_ORIGIN
}

export function allowsProductionLive({
  viteApiUrl,
  enableLiveProduction,
  vercelEnv,
} = {}) {
  return (
    isLiveProductionOptIn(enableLiveProduction)
    && String(vercelEnv || '').toLowerCase() === 'production'
    && isExactProductionApiUrl(viteApiUrl)
  )
}

export function isProductionWsUrl(url) {
  return isProductionApiUrl(url)
}

export function httpUrlToWs(apiBase) {
  const trimmed = String(apiBase || '').trim().replace(/\/$/, '')
  if (!trimmed) return null
  if (/^https:/i.test(trimmed)) return `${trimmed.replace(/^https:/i, 'wss:')}/live`
  if (/^http:/i.test(trimmed)) return `${trimmed.replace(/^http:/i, 'ws:')}/live`
  if (/^wss:/i.test(trimmed) || /^ws:/i.test(trimmed)) {
    return /\/live$/i.test(trimmed) ? trimmed : `${trimmed}/live`
  }
  return `${trimmed}/live`
}

export function isPreviewEnv({ vercelEnv, pageHost, mode } = {}) {
  const ve = String(vercelEnv || '').toLowerCase()
  if (ve === 'production') return false
  if (ve === 'preview') return true
  const host = String(pageHost || '')
  if (/\.vercel\.app$/i.test(host)) return true
  return String(mode || '') === 'preview'
}

export function resolveLiveConfig({
  viteApiUrl,
  mode,
  dev,
  vercelEnv,
  pageHost,
  enableLiveProduction,
} = {}) {
  const raw = String(viteApiUrl ?? '').trim()
  const preview = isPreviewEnv({ vercelEnv, pageHost, mode })
  const productionLike = mode === 'production' || preview
  const productionLive = allowsProductionLive({
    viteApiUrl: raw,
    enableLiveProduction,
    vercelEnv,
  })

  if (raw && isProductionApiUrl(raw) && !productionLive) {
    return {
      ok: false,
      blocked: true,
      reason: 'production_api_blocked',
      apiBase: raw,
      wsUrl: null,
      message: LIVE_CONFIG_MESSAGES.production_api_blocked,
    }
  }

  if (!raw) {
    if (productionLike) {
      return {
        ok: false,
        blocked: true,
        reason: 'missing_vite_api_url',
        apiBase: '',
        wsUrl: null,
        message: LIVE_CONFIG_MESSAGES.missing_vite_api_url,
      }
    }
    if (pageHost && isProductionApiUrl(`https://${pageHost}`)) {
      return {
        ok: false,
        blocked: true,
        reason: 'production_api_blocked',
        apiBase: '',
        wsUrl: null,
        message: LIVE_CONFIG_MESSAGES.production_api_blocked,
      }
    }
    return {
      ok: true,
      blocked: false,
      reason: 'dev_proxy',
      apiBase: '',
      wsUrl: null,
      usePageHost: true,
      message: null,
    }
  }

  const wsUrl = httpUrlToWs(raw)
  if (wsUrl && isProductionWsUrl(wsUrl) && !productionLive) {
    return {
      ok: false,
      blocked: true,
      reason: 'production_api_blocked',
      apiBase: raw,
      wsUrl: null,
      message: LIVE_CONFIG_MESSAGES.production_api_blocked,
    }
  }

  return {
    ok: true,
    blocked: false,
    reason: productionLive ? 'production_opt_in' : 'configured',
    apiBase: raw.replace(/\/$/, ''),
    wsUrl,
    usePageHost: false,
    message: null,
  }
}

function readViteEnv() {
  try {
    return import.meta.env || {}
  } catch {
    return {}
  }
}

export function getLiveRuntimeConfig() {
  const env = readViteEnv()
  let pageHost = ''
  try {
    pageHost = window.location.hostname
  } catch {
    pageHost = ''
  }
  return resolveLiveConfig({
    viteApiUrl: env.VITE_API_URL,
    mode: env.MODE,
    dev: env.DEV,
    vercelEnv: env.VITE_VERCEL_ENV,
    pageHost,
    enableLiveProduction: env.VITE_ENABLE_LIVE_PRODUCTION,
  })
}

export function livePageWsUrl(location = (typeof window !== 'undefined' ? window.location : null)) {
  const proto = location && location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = location ? location.host : 'localhost'
  if (isProductionApiUrl(`${proto}//${host}`)) {
    throw new Error(LIVE_CONFIG_MESSAGES.production_api_blocked)
  }
  return `${proto}//${host}/live`
}
