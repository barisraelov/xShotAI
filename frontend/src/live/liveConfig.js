/** Live API / WebSocket configuration (FIX-05 / LIVE-25). Never default to Production. */

export const PRODUCTION_API_HOSTS = ['xshotai.up.railway.app']

export const LIVE_CONFIG_MESSAGES = {
  missing_vite_api_url:
    'Live is not configured: missing VITE_API_URL. Preview must point at Staging, never Production.',
  preview_points_at_production:
    'Live is blocked: this Preview build points at the Production API. Use the Staging URL.',
}

export function isProductionApiUrl(url) {
  if (!url) return false
  try {
    const host = new URL(url).hostname.toLowerCase()
    return PRODUCTION_API_HOSTS.includes(host)
  } catch {
    return PRODUCTION_API_HOSTS.some(h => String(url).toLowerCase().includes(h))
  }
}

export function httpUrlToWs(apiBase) {
  const trimmed = String(apiBase || '').trim().replace(/\/$/, '')
  if (!trimmed) return null
  if (/^https:/i.test(trimmed)) return `${trimmed.replace(/^https:/i, 'wss:')}/live`
  if (/^http:/i.test(trimmed)) return `${trimmed.replace(/^http:/i, 'ws:')}/live`
  return `${trimmed}/live`
}

export function isPreviewEnv({ vercelEnv, pageHost, mode } = {}) {
  if (String(vercelEnv || '').toLowerCase() === 'preview') return true
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
} = {}) {
  const raw = String(viteApiUrl ?? '').trim()
  const preview = isPreviewEnv({ vercelEnv, pageHost, mode })
  const productionLike = mode === 'production' || preview

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

  if (preview && isProductionApiUrl(raw)) {
    return {
      ok: false,
      blocked: true,
      reason: 'preview_points_at_production',
      apiBase: raw,
      wsUrl: null,
      message: LIVE_CONFIG_MESSAGES.preview_points_at_production,
    }
  }

  return {
    ok: true,
    blocked: false,
    reason: 'configured',
    apiBase: raw.replace(/\/$/, ''),
    wsUrl: httpUrlToWs(raw),
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
  })
}

export function livePageWsUrl(location = (typeof window !== 'undefined' ? window.location : null)) {
  const proto = location && location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = location ? location.host : 'localhost'
  return `${proto}//${host}/live`
}
