import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  PRODUCTION_API_HOSTS,
  httpUrlToWs,
  isProductionApiUrl,
  resolveLiveConfig,
} from './liveConfig.js'

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = join(here, '..', '..')

describe('FIX-05 Live config must not default to Production', () => {
  it('Preview / production-like build without VITE_API_URL is blocked and has no Production URL', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: '',
      mode: 'production',
      vercelEnv: 'preview',
      pageHost: 'xshot-git-feature-realtime-feedback.vercel.app',
    })
    assert.equal(cfg.ok, false)
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.reason, 'missing_vite_api_url')
    assert.equal(cfg.wsUrl, null)
    assert.equal(cfg.apiBase, '')
    assert.equal(isProductionApiUrl(cfg.apiBase), false)
    assert.equal(PRODUCTION_API_HOSTS.includes('xshotai.up.railway.app'), true)
  })

  it('HTTPS Staging becomes WSS Staging', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshot-staging.up.railway.app',
      mode: 'production',
      vercelEnv: 'preview',
      pageHost: 'example.vercel.app',
    })
    assert.equal(cfg.ok, true)
    assert.equal(cfg.wsUrl, 'wss://xshot-staging.up.railway.app/live')
    assert.equal(
      httpUrlToWs('https://xshot-staging.up.railway.app/'),
      'wss://xshot-staging.up.railway.app/live',
    )
  })

  it('does not put a Production URL on the Live path as a default', () => {
    const dev = resolveLiveConfig({ viteApiUrl: '', mode: 'development', dev: true })
    assert.equal(dev.ok, true)
    assert.equal(dev.usePageHost, true)
    assert.equal(dev.wsUrl, null)
    assert.equal(isProductionApiUrl(dev.apiBase), false)

    const example = readFileSync(join(frontendRoot, '.env.example'), 'utf8')
    assert.doesNotMatch(example, /^\s*VITE_API_URL\s*=\s*https?:\/\/xshotai\.up\.railway\.app/m)
    assert.match(example, /^VITE_API_URL=\s*$/m)
  })

  it('blocks a Preview build that points at Production', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshotai.up.railway.app',
      mode: 'production',
      vercelEnv: 'preview',
      pageHost: 'example.vercel.app',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.reason, 'production_api_blocked')
    assert.equal(cfg.wsUrl, null)
  })
})

describe('PATCH-04 Live blocks Production in every environment', () => {
  it('blocks Preview against Production', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshotai.up.railway.app',
      mode: 'production',
      vercelEnv: 'preview',
      pageHost: 'xshot-git-feature.vercel.app',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.wsUrl, null)
  })

  it('blocks a custom domain without VITE_VERCEL_ENV against Production', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshotai.up.railway.app',
      mode: 'production',
      vercelEnv: '',
      pageHost: 'live.xshot.app',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.reason, 'production_api_blocked')
    assert.equal(cfg.wsUrl, null)
  })

  it('blocks environment=production against Production', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshotai.up.railway.app',
      mode: 'production',
      vercelEnv: 'production',
      pageHost: 'xshot.app',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(isProductionApiUrl(cfg.apiBase), true)
    assert.equal(cfg.wsUrl, null)
  })

  it('blocks Production WSS', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'wss://xshotai.up.railway.app/live',
      mode: 'development',
      vercelEnv: '',
      pageHost: 'localhost',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.wsUrl, null)
    assert.equal(isProductionApiUrl('wss://xshotai.up.railway.app/live'), true)
  })

  it('allows Staging HTTPS and WSS', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshot-staging.up.railway.app',
      mode: 'production',
      vercelEnv: '',
      pageHost: 'custom.example.com',
    })
    assert.equal(cfg.ok, true)
    assert.equal(cfg.blocked, false)
    assert.equal(cfg.wsUrl, 'wss://xshot-staging.up.railway.app/live')
  })

  it('allows localhost', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'http://localhost:8000',
      mode: 'development',
      dev: true,
      pageHost: 'localhost',
    })
    assert.equal(cfg.ok, true)
    assert.equal(cfg.wsUrl, 'ws://localhost:8000/live')
    const proxy = resolveLiveConfig({ viteApiUrl: '', mode: 'development', dev: true, pageHost: 'localhost' })
    assert.equal(proxy.ok, true)
    assert.equal(proxy.usePageHost, true)
  })

  it('does not change Upload API_BASE configuration', () => {
    const auth = readFileSync(join(frontendRoot, 'src', 'auth.js'), 'utf8')
    assert.match(auth, /export const API_BASE = import\.meta\.env\.VITE_API_URL \|\| ''/)
    assert.doesNotMatch(auth, /liveConfig/)
    assert.doesNotMatch(auth, /PRODUCTION_API_HOSTS/)
  })
})

describe('Production Live opt-in (VITE_ENABLE_LIVE_PRODUCTION)', () => {
  const productionUrl = 'https://xshotai.up.railway.app'

  it('allows Production Live only with explicit opt-in on Vercel Production', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: productionUrl,
      mode: 'production',
      vercelEnv: 'production',
      pageHost: 'x-shot-ai.vercel.app',
      enableLiveProduction: 'true',
    })
    assert.equal(cfg.ok, true)
    assert.equal(cfg.blocked, false)
    assert.equal(cfg.reason, 'production_opt_in')
    assert.equal(cfg.apiBase, productionUrl)
    assert.equal(cfg.wsUrl, 'wss://xshotai.up.railway.app/live')
  })

  it('still blocks Production without the opt-in flag', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: productionUrl,
      mode: 'production',
      vercelEnv: 'production',
      pageHost: 'x-shot-ai.vercel.app',
      enableLiveProduction: '',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.wsUrl, null)
  })

  it('still blocks Preview even if the opt-in flag is set', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: productionUrl,
      mode: 'production',
      vercelEnv: 'preview',
      pageHost: 'xshot-live-staging.vercel.app',
      enableLiveProduction: 'true',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.wsUrl, null)
  })

  it('rejects a non-exact Production URL even with opt-in', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshotai.up.railway.app/extra',
      mode: 'production',
      vercelEnv: 'production',
      pageHost: 'x-shot-ai.vercel.app',
      enableLiveProduction: 'true',
    })
    assert.equal(cfg.blocked, true)
    assert.equal(cfg.wsUrl, null)
  })

  it('keeps Staging on the Staging backend without opt-in', () => {
    const cfg = resolveLiveConfig({
      viteApiUrl: 'https://xshot-staging-backend-production.up.railway.app',
      mode: 'production',
      vercelEnv: 'preview',
      pageHost: 'xshot-live-staging.vercel.app',
    })
    assert.equal(cfg.ok, true)
    assert.equal(
      cfg.wsUrl,
      'wss://xshot-staging-backend-production.up.railway.app/live',
    )
  })
})
