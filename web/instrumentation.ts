// Server/edge-side Sentry init via Next's native instrumentation hook (no withSentryConfig).
// Disabled unless NEXT_PUBLIC_SENTRY_DSN is set. `onRequestError` forwards errors thrown in
// server components / route handlers to Sentry (no-op when uninitialized).
import * as Sentry from '@sentry/nextjs'

export async function register() {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN
  if (!dsn) return
  if (process.env.NEXT_RUNTIME === 'nodejs' || process.env.NEXT_RUNTIME === 'edge') {
    Sentry.init({
      dsn,
      environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'production',
      release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
      tracesSampleRate: 0,
      sendDefaultPii: false,
    })
  }
}

export const onRequestError = Sentry.captureRequestError
