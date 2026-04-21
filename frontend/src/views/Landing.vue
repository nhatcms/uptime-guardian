<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import PricingTable from '@/components/PricingTable.vue'
import { plansApi } from '@/api'

// Public marketing landing page (Requirement 19).
//
// Fetches the active plans and renders a pricing table. When no plans exist a
// placeholder message is shown instead of the table (Req 19.3); when the fetch
// fails, the placeholder plus an error banner are shown while the rest of the
// page stays intact (Req 19.4). The primary CTA routes to the registration
// page (Req 19.5, 19.6).
const plans = ref([])
const loading = ref(true)
const loadError = ref(false)

const mobileMenuOpen = ref(false)

// --- Live dashboard mockup (animated) -----------------------------------

const mockMonitors = reactive([
  { name: 'api.acme.io', status: 'up', latency: 142, uptime: '99.98%' },
  { name: 'app.acme.io', status: 'up', latency: 88, uptime: '99.99%' },
  { name: 'checkout.acme.io', status: 'degraded', latency: 612, uptime: '99.71%' },
  { name: 'cdn.acme.io', status: 'up', latency: 31, uptime: '100%' },
])

// A rolling window of the last N check results, shifted on an interval to fake
// a realtime feed. `fresh` marks the most recently pushed bar so it can pulse.
const BAR_COUNT = 44
const bars = ref(
  Array.from({ length: BAR_COUNT }, (_, i) => ({
    status: i === 11 || i === 31 ? 'down' : i === 19 ? 'degraded' : 'up',
    fresh: false,
  })),
)

function nextStatus() {
  const r = Math.random()
  if (r > 0.94) return 'down'
  if (r > 0.85) return 'degraded'
  return 'up'
}

let barTimer = null
let latencyTimer = null

function tickBars() {
  const arr = bars.value.slice(1).map((b) => ({ ...b, fresh: false }))
  arr.push({ status: nextStatus(), fresh: true })
  bars.value = arr
}

function tickLatency() {
  for (const m of mockMonitors) {
    // Small random walk around a per-monitor baseline.
    const base = m.name === 'checkout.acme.io' ? 560 : m.name === 'cdn.acme.io' ? 34 : 110
    const jitter = Math.round((Math.random() - 0.5) * 90)
    m.latency = Math.max(8, base + jitter)
    m.status = m.latency > 450 ? 'degraded' : 'up'
  }
}

// --- Count-up stats ------------------------------------------------------

const stats = reactive([
  { target: 30, decimals: 0, prefix: '', suffix: 's', label: 'Min check interval', display: 0 },
  { target: 24, decimals: 0, prefix: '', suffix: '/7', label: 'Always-on probing', display: 0 },
  { target: 10, decimals: 0, prefix: '<', suffix: 's', label: 'Alert latency', display: 0 },
  { target: 99.9, decimals: 1, prefix: '', suffix: '%', label: 'Platform uptime', display: 0 },
])

function formatStat(s) {
  return `${s.prefix}${s.display.toFixed(s.decimals)}${s.suffix}`
}

let statsAnimated = false
function animateStats() {
  if (statsAnimated) return
  statsAnimated = true
  const duration = 1400
  const start = typeof performance !== 'undefined' ? performance.now() : Date.now()
  const raf = typeof requestAnimationFrame !== 'undefined' ? requestAnimationFrame : (cb) => setTimeout(() => cb(Date.now()), 16)

  function frame(now) {
    const t = Math.min(1, (now - start) / duration)
    const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic
    for (const s of stats) s.display = s.target * eased
    if (t < 1) raf(frame)
    else for (const s of stats) s.display = s.target
  }
  raf(frame)
}

const statsEl = ref(null)
let statsObserver = null

// --- Plans ---------------------------------------------------------------

async function loadPlans() {
  loading.value = true
  loadError.value = false
  try {
    const { data } = await plansApi.list()
    plans.value = Array.isArray(data) ? data : []
  } catch {
    loadError.value = true
    plans.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadPlans()

  // Realtime mockup feeds.
  barTimer = setInterval(tickBars, 900)
  latencyTimer = setInterval(tickLatency, 1600)

  // Count-up when the stats row scrolls into view (fallback: animate now).
  if (typeof IntersectionObserver !== 'undefined' && statsEl.value) {
    statsObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          animateStats()
          statsObserver?.disconnect()
        }
      },
      { threshold: 0.3 },
    )
    statsObserver.observe(statsEl.value)
  } else {
    animateStats()
  }
})

onBeforeUnmount(() => {
  if (barTimer) clearInterval(barTimer)
  if (latencyTimer) clearInterval(latencyTimer)
  statsObserver?.disconnect()
})

// --- Static content ------------------------------------------------------

const features = [
  { icon: '📡', title: 'Global uptime probes', body: 'Round-the-clock HTTP/TCP checks from distributed probes detect outages before your users ever notice.', tag: 'monitoring' },
  { icon: '⚡', title: 'Realtime Telegram alerts', body: 'Down and recovery events stream straight to Telegram in seconds — no noisy digests, just signal.', tag: 'alerting' },
  { icon: '🔒', title: 'TLS / SSL watchdog', body: 'Certificate chains are inspected continuously and you are warned long before anything expires.', tag: 'security' },
  { icon: '📈', title: 'Latency analytics', body: 'High-resolution response-time history and uptime bars surface slowdowns and regressions instantly.', tag: 'analytics' },
  { icon: '🧠', title: 'Smart incident logic', body: 'Confirmation re-checks and recovery detection keep false positives out of your inbox.', tag: 'engine' },
  { icon: '🛰️', title: 'Zero-agent setup', body: 'No daemons, no sidecars. Paste a URL, choose an interval, and monitoring is live in seconds.', tag: 'platform' },
]

const steps = [
  { number: '01', title: 'Register an endpoint', body: 'Add any URL and pick a check interval down to the second.' },
  { number: '02', title: 'Wire up Telegram', body: 'Link your chat once so alerts reach you anywhere instantly.' },
  { number: '03', title: 'Ship with confidence', body: 'We probe continuously and page you the moment health degrades.' },
]

const stack = ['HTTP', 'HTTPS', 'TCP', 'TLS/SSL', 'Telegram', 'Webhooks', 'REST API', 'Cron']

const faqs = [
  { q: 'How quickly will I be notified of downtime?', a: 'As soon as a confirmed check fails we push a Telegram alert — typically within seconds of detection.' },
  { q: 'Do I need to install anything?', a: 'No. Uptime Guardian runs entirely in the cloud. Add a URL and you are monitoring — no agents or scripts.' },
  { q: 'Can I monitor SSL certificate expiry?', a: 'Yes. On supported plans we track certificate validity and warn you well before anything expires.' },
  { q: 'Is there a free plan?', a: 'Yes. Start for free and upgrade whenever you need more monitors or shorter check intervals.' },
]
</script>

<template>
  <div class="relative min-h-screen overflow-hidden bg-bg text-slate-100">
    <!-- ===================== Ambient background ===================== -->
    <div class="pointer-events-none fixed inset-0 -z-10" aria-hidden="true">
      <div class="absolute inset-0 bg-grid opacity-[0.18]"></div>
      <div class="absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-up/25 blur-[140px] anim-pulse-glow"></div>
      <div class="absolute top-1/3 -right-40 h-[420px] w-[420px] rounded-full bg-emerald-400/10 blur-[140px]"></div>
      <div class="absolute inset-x-0 bottom-0 h-64 bg-gradient-to-t from-bg to-transparent"></div>
    </div>

    <!-- ===================== Navbar ===================== -->
    <header class="sticky top-0 z-50 border-b border-slate-800/60 bg-bg/70 backdrop-blur-xl">
      <nav class="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
        <a href="#top" class="flex items-center gap-2">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-up/15 text-up ring-1 ring-up/30 neon-ring">📡</span>
          <span class="font-mono text-lg font-bold tracking-tight text-slate-100">Uptime<span class="text-up neon-text">Guardian</span></span>
        </a>

        <div class="hidden items-center gap-8 md:flex">
          <a href="#features" class="text-sm text-slate-300 transition hover:text-up">Features</a>
          <a href="#preview" class="text-sm text-slate-300 transition hover:text-up">Platform</a>
          <a href="#how" class="text-sm text-slate-300 transition hover:text-up">How it works</a>
          <a href="#pricing" class="text-sm text-slate-300 transition hover:text-up">Pricing</a>
          <a href="#faq" class="text-sm text-slate-300 transition hover:text-up">FAQ</a>
        </div>

        <div class="hidden items-center gap-3 md:flex">
          <router-link :to="{ name: 'login' }" class="text-sm font-medium text-slate-300 transition hover:text-up">Sign in</router-link>
          <router-link
            :to="{ name: 'register' }"
            class="rounded-lg bg-up px-4 py-2 text-sm font-semibold text-bg shadow-lg shadow-up/30 transition hover:bg-up/90 neon-btn"
          >
            Get started
          </router-link>
        </div>

        <button
          type="button"
          class="grid h-9 w-9 place-items-center rounded-lg border border-slate-800 text-slate-300 md:hidden"
          aria-label="Toggle navigation"
          @click="mobileMenuOpen = !mobileMenuOpen"
        >
          <span v-if="!mobileMenuOpen">☰</span>
          <span v-else>✕</span>
        </button>
      </nav>

      <div v-if="mobileMenuOpen" class="border-t border-slate-800/60 px-4 py-4 md:hidden">
        <div class="flex flex-col gap-3">
          <a href="#features" class="text-sm text-slate-300" @click="mobileMenuOpen = false">Features</a>
          <a href="#preview" class="text-sm text-slate-300" @click="mobileMenuOpen = false">Platform</a>
          <a href="#how" class="text-sm text-slate-300" @click="mobileMenuOpen = false">How it works</a>
          <a href="#pricing" class="text-sm text-slate-300" @click="mobileMenuOpen = false">Pricing</a>
          <a href="#faq" class="text-sm text-slate-300" @click="mobileMenuOpen = false">FAQ</a>
          <div class="mt-2 flex gap-3">
            <router-link :to="{ name: 'login' }" class="flex-1 rounded-lg border border-slate-700 px-4 py-2 text-center text-sm font-medium text-slate-200">Sign in</router-link>
            <router-link :to="{ name: 'register' }" class="flex-1 rounded-lg bg-up px-4 py-2 text-center text-sm font-semibold text-bg">Get started</router-link>
          </div>
        </div>
      </div>
    </header>

    <!-- ===================== Hero ===================== -->
    <section id="top" class="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-20 pb-16 sm:px-6 lg:grid-cols-2 lg:pt-28">
      <div>
        <span class="inline-flex items-center gap-2 rounded-full border border-up/30 bg-up/10 px-4 py-1.5 font-mono text-xs font-medium text-up neon-text">
          <span class="h-2 w-2 animate-ping rounded-full bg-up"></span>
          systems.operational // monitoring 24/7
        </span>

        <h1 class="mt-6 font-mono text-4xl font-bold leading-tight tracking-tight text-slate-50 sm:text-5xl">
          Observe everything.
          <br />
          <span class="text-up neon-text-strong">Miss nothing.</span>
        </h1>

        <p class="mt-6 max-w-xl text-lg text-slate-300">
          A high-signal uptime platform that probes your endpoints around the
          clock, tracks SSL health, and streams incidents to Telegram in
          real time.
        </p>

        <div class="mt-9 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
          <router-link
            :to="{ name: 'register' }"
            data-testid="cta-register"
            class="inline-flex items-center gap-2 rounded-lg bg-up px-7 py-3 text-lg font-semibold text-bg shadow-lg shadow-up/30 transition hover:bg-up/90 neon-btn"
          >
            Get started free <span aria-hidden="true">→</span>
          </router-link>
          <a href="#preview" class="inline-block rounded-lg border border-slate-700 px-7 py-3 text-lg font-medium text-slate-200 transition hover:border-up/50 hover:text-up">
            Explore the platform
          </a>
        </div>

        <p class="mt-4 font-mono text-sm text-slate-500">$ no credit card required · free tier available</p>
      </div>

      <!-- live dashboard mockup -->
      <div id="preview" class="relative">
        <div class="absolute -inset-4 -z-10 rounded-3xl bg-up/10 blur-2xl anim-pulse-glow"></div>
        <div class="overflow-hidden rounded-2xl border border-up/20 bg-slate-900/70 shadow-2xl backdrop-blur neon-panel">
          <div class="flex items-center gap-2 border-b border-slate-800 bg-slate-900/80 px-4 py-3">
            <span class="h-3 w-3 rounded-full bg-down/80"></span>
            <span class="h-3 w-3 rounded-full bg-yellow-400/80"></span>
            <span class="h-3 w-3 rounded-full bg-up/80"></span>
            <span class="ml-3 font-mono text-xs text-slate-500">guardian — live status</span>
            <span class="ml-auto flex items-center gap-1.5 font-mono text-xs text-up">
              <span class="h-1.5 w-1.5 animate-ping rounded-full bg-up"></span> live
            </span>
          </div>

          <div class="divide-y divide-slate-800/70">
            <div v-for="m in mockMonitors" :key="m.name" class="flex items-center gap-3 px-4 py-3">
              <span
                class="h-2.5 w-2.5 rounded-full transition-colors"
                :class="m.status === 'up' ? 'bg-up neon-dot' : m.status === 'degraded' ? 'bg-yellow-400' : 'bg-down'"
              ></span>
              <span class="font-mono text-sm text-slate-200">{{ m.name }}</span>
              <span class="ml-auto font-mono text-xs tabular-nums text-slate-400 transition-all">{{ m.latency }}ms</span>
              <span
                class="w-16 text-right font-mono text-xs tabular-nums"
                :class="m.status === 'up' ? 'text-up' : m.status === 'degraded' ? 'text-yellow-400' : 'text-down'"
              >{{ m.uptime }}</span>
            </div>
          </div>

          <div class="border-t border-slate-800 px-4 py-4">
            <p class="mb-2 font-mono text-xs text-slate-500">live check feed</p>
            <div class="flex items-end gap-[3px]">
              <span
                v-for="(b, i) in bars"
                :key="i"
                class="h-7 flex-1 rounded-sm transition-all duration-500"
                :class="[
                  b.status === 'up' ? 'bg-up/70' : b.status === 'degraded' ? 'bg-yellow-400/70' : 'bg-down/80',
                  b.fresh ? 'anim-bar-in shadow-[0_0_10px_rgba(0,212,170,0.8)]' : '',
                ]"
              ></span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ===================== Tech stack ===================== -->
    <section class="border-y border-slate-800/60 bg-slate-900/30">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-8 gap-y-3 px-4 py-6 sm:px-6">
        <span class="font-mono text-xs uppercase tracking-widest text-slate-600">speaks</span>
        <span v-for="proto in stack" :key="proto" class="font-mono text-sm text-slate-400 transition hover:text-up hover:neon-text">{{ proto }}</span>
      </div>
    </section>

    <!-- ===================== Stats (count-up) ===================== -->
    <section class="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <dl ref="statsEl" class="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-slate-800 bg-slate-800 sm:grid-cols-4">
        <div v-for="stat in stats" :key="stat.label" class="bg-slate-900/60 px-4 py-7 text-center">
          <dt class="font-mono text-3xl font-bold tabular-nums text-up neon-text">{{ formatStat(stat) }}</dt>
          <dd class="mt-1 text-xs text-slate-400 sm:text-sm">{{ stat.label }}</dd>
        </div>
      </dl>
    </section>

    <!-- ===================== Features ===================== -->
    <section id="features" class="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <div class="mx-auto max-w-2xl text-center">
        <p class="font-mono text-sm uppercase tracking-widest text-up neon-text">// capabilities</p>
        <h2 class="mt-3 text-3xl font-bold text-slate-50 sm:text-4xl">A full-stack observability toolkit</h2>
        <p class="mt-4 text-slate-400">Everything you need to detect, diagnose, and recover — without the operational overhead.</p>
      </div>

      <div class="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-2xl border border-slate-800 bg-slate-800 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="feature in features" :key="feature.title" class="group relative bg-slate-900/50 p-7 transition hover:bg-slate-900/90">
          <div class="flex items-center justify-between">
            <div class="grid h-11 w-11 place-items-center rounded-xl bg-up/10 text-xl ring-1 ring-up/20 transition group-hover:neon-ring">{{ feature.icon }}</div>
            <span class="font-mono text-[11px] uppercase tracking-wider text-slate-600 group-hover:text-up">{{ feature.tag }}</span>
          </div>
          <h3 class="mt-5 text-lg font-semibold text-slate-100">{{ feature.title }}</h3>
          <p class="mt-2 text-sm leading-relaxed text-slate-400">{{ feature.body }}</p>
        </div>
      </div>
    </section>

    <!-- ===================== Code / webhook block ===================== -->
    <section class="border-y border-slate-800/60 bg-slate-900/20">
      <div class="mx-auto grid max-w-6xl items-center gap-12 px-4 py-20 sm:px-6 lg:grid-cols-2">
        <div>
          <p class="font-mono text-sm uppercase tracking-widest text-up neon-text">// developer first</p>
          <h2 class="mt-3 text-3xl font-bold text-slate-50 sm:text-4xl">Alerts that fit your workflow</h2>
          <p class="mt-4 text-slate-400">
            Every incident is delivered as a structured event. Pipe it into
            Telegram out of the box, or fan it out to your own webhook for
            on-call routing, dashboards, and automation.
          </p>
          <ul class="mt-6 space-y-3 text-sm text-slate-300">
            <li class="flex items-start gap-2"><span class="text-up">▹</span> Structured JSON payloads for every state change</li>
            <li class="flex items-start gap-2"><span class="text-up">▹</span> Down, recovery, and SSL-expiry event types</li>
            <li class="flex items-start gap-2"><span class="text-up">▹</span> Confirmation re-checks to kill false alarms</li>
          </ul>
        </div>

        <div class="overflow-hidden rounded-2xl border border-up/20 bg-[#0b1120] shadow-2xl neon-panel">
          <div class="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
            <span class="h-3 w-3 rounded-full bg-down/80"></span>
            <span class="h-3 w-3 rounded-full bg-yellow-400/80"></span>
            <span class="h-3 w-3 rounded-full bg-up/80"></span>
            <span class="ml-3 font-mono text-xs text-slate-500">incident.json</span>
          </div>
          <pre class="overflow-x-auto p-5 font-mono text-[13px] leading-relaxed"><code><span class="text-slate-600"># POST → your webhook</span>
<span class="text-slate-500">{</span>
  <span class="text-up">"event"</span>: <span class="text-yellow-300">"monitor.down"</span>,
  <span class="text-up">"monitor"</span>: <span class="text-yellow-300">"api.acme.io"</span>,
  <span class="text-up">"status_code"</span>: <span class="text-indigo-300">503</span>,
  <span class="text-up">"latency_ms"</span>: <span class="text-indigo-300">8042</span>,
  <span class="text-up">"ssl_days_left"</span>: <span class="text-indigo-300">27</span>,
  <span class="text-up">"detected_at"</span>: <span class="text-yellow-300">"2026-06-07T04:12:09Z"</span>
<span class="text-slate-500">}</span></code></pre>
        </div>
      </div>
    </section>

    <!-- ===================== How it works ===================== -->
    <section id="how" class="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <div class="mx-auto max-w-2xl text-center">
        <p class="font-mono text-sm uppercase tracking-widest text-up neon-text">// pipeline</p>
        <h2 class="mt-3 text-3xl font-bold text-slate-50 sm:text-4xl">Live in three steps</h2>
      </div>

      <div class="mt-14 grid grid-cols-1 gap-8 md:grid-cols-3">
        <div v-for="step in steps" :key="step.number" class="relative rounded-2xl border border-slate-800 bg-slate-900/40 p-7 transition hover:border-up/40">
          <span class="font-mono text-5xl font-bold text-up/20">{{ step.number }}</span>
          <h3 class="mt-3 text-lg font-semibold text-slate-100">{{ step.title }}</h3>
          <p class="mt-2 text-sm leading-relaxed text-slate-400">{{ step.body }}</p>
        </div>
      </div>
    </section>

    <!-- ===================== Pricing ===================== -->
    <section id="pricing" class="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <div class="mx-auto max-w-2xl text-center">
        <p class="font-mono text-sm uppercase tracking-widest text-up neon-text">// pricing</p>
        <h2 class="mt-3 text-3xl font-bold text-slate-50 sm:text-4xl">Scale when you need to</h2>
        <p class="mt-4 text-slate-400">Start free. Upgrade only when you need more monitors or faster checks.</p>
      </div>

      <div class="mt-14">
        <p
          v-if="loadError"
          role="alert"
          data-testid="pricing-error"
          class="mx-auto mb-6 max-w-md rounded-lg border border-down/40 bg-down/10 px-4 py-3 text-center text-sm text-down"
        >
          Pricing could not be loaded right now. Please try again later.
        </p>

        <div v-if="loading" class="text-center font-mono text-slate-500">Loading plans…</div>

        <p
          v-else-if="plans.length === 0"
          data-testid="pricing-placeholder"
          class="text-center text-slate-400"
        >
          Pricing is not currently available.
        </p>

        <PricingTable v-else :plans="plans" />
      </div>
    </section>

    <!-- ===================== FAQ ===================== -->
    <section id="faq" class="border-t border-slate-800/60 bg-slate-900/20">
      <div class="mx-auto max-w-3xl px-4 py-20 sm:px-6">
        <div class="mx-auto max-w-2xl text-center">
          <p class="font-mono text-sm uppercase tracking-widest text-up neon-text">// faq</p>
          <h2 class="mt-3 text-3xl font-bold text-slate-50 sm:text-4xl">Frequently asked questions</h2>
        </div>

        <div class="mt-12 space-y-4">
          <details v-for="faq in faqs" :key="faq.q" class="group rounded-xl border border-slate-800 bg-slate-900/40 p-5 [&_summary::-webkit-details-marker]:hidden">
            <summary class="flex cursor-pointer items-center justify-between gap-4 text-base font-medium text-slate-100">
              {{ faq.q }}
              <span class="text-up transition group-open:rotate-45">+</span>
            </summary>
            <p class="mt-3 text-sm leading-relaxed text-slate-400">{{ faq.a }}</p>
          </details>
        </div>
      </div>
    </section>

    <!-- ===================== Final CTA ===================== -->
    <section class="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <div class="relative overflow-hidden rounded-3xl border border-up/30 bg-gradient-to-br from-up/15 via-slate-900/50 to-bg px-6 py-16 text-center sm:px-12 neon-panel">
        <div class="absolute inset-0 -z-10 bg-grid opacity-10" aria-hidden="true"></div>
        <h2 class="text-3xl font-bold text-slate-50 sm:text-4xl">Stop hearing it from your customers first</h2>
        <p class="mx-auto mt-4 max-w-xl text-slate-300">Deploy your first probe in minutes and let Uptime Guardian keep watch around the clock.</p>
        <router-link
          :to="{ name: 'register' }"
          class="mt-8 inline-flex items-center gap-2 rounded-lg bg-up px-8 py-3 text-lg font-semibold text-bg shadow-lg shadow-up/30 transition hover:bg-up/90 neon-btn"
        >
          Get started free <span aria-hidden="true">→</span>
        </router-link>
      </div>
    </section>

    <!-- ===================== Footer ===================== -->
    <footer class="border-t border-slate-800/60">
      <div class="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 sm:flex-row sm:px-6">
        <div class="flex items-center gap-2">
          <span class="grid h-7 w-7 place-items-center rounded-lg bg-up/15 text-up ring-1 ring-up/30">📡</span>
          <span class="font-mono text-sm font-semibold text-slate-200">UptimeGuardian</span>
        </div>
        <div class="flex items-center gap-6 text-sm text-slate-400">
          <a href="#features" class="transition hover:text-up">Features</a>
          <a href="#pricing" class="transition hover:text-up">Pricing</a>
          <router-link :to="{ name: 'login' }" class="transition hover:text-up">Sign in</router-link>
        </div>
        <p class="font-mono text-xs text-slate-600">© {{ new Date().getFullYear() }} UptimeGuardian</p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.bg-grid {
  background-image:
    linear-gradient(to right, rgba(0, 212, 170, 0.07) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(0, 212, 170, 0.07) 1px, transparent 1px);
  background-size: 44px 44px;
}

/* Neon accents built on the existing `up` token (#00d4aa). */
.neon-text {
  text-shadow: 0 0 8px rgba(0, 212, 170, 0.55);
}
.neon-text-strong {
  text-shadow:
    0 0 10px rgba(0, 212, 170, 0.7),
    0 0 28px rgba(0, 212, 170, 0.45);
}
.neon-ring {
  box-shadow:
    0 0 0 1px rgba(0, 212, 170, 0.4),
    0 0 18px rgba(0, 212, 170, 0.35);
}
.neon-btn {
  box-shadow:
    0 0 18px rgba(0, 212, 170, 0.45),
    0 0 40px rgba(0, 212, 170, 0.2);
}
.neon-panel {
  box-shadow:
    0 0 0 1px rgba(0, 212, 170, 0.12),
    0 20px 60px -20px rgba(0, 212, 170, 0.35);
}
.neon-dot {
  box-shadow: 0 0 8px rgba(0, 212, 170, 0.9);
}

/* Animations */
@keyframes pulseGlow {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
.anim-pulse-glow {
  animation: pulseGlow 4s ease-in-out infinite;
}

@keyframes barIn {
  0% { transform: scaleY(0.15); opacity: 0.3; }
  60% { transform: scaleY(1.15); }
  100% { transform: scaleY(1); opacity: 1; }
}
.anim-bar-in {
  transform-origin: bottom;
  animation: barIn 0.55s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .anim-pulse-glow,
  .anim-bar-in {
    animation: none;
  }
}
</style>
