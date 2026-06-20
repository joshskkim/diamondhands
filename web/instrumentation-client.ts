// Client-side Sentry init. Next runs this in the browser (native instrumentation-client hook,
// no withSentryConfig needed). Disabled unless NEXT_PUBLIC_SENTRY_DSN is baked in at build time,
// so dev and un-configured builds send nothing.
import * as Sentry from '@sentry/nextjs'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'production',
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
    // Errors are captured by default; performance/replay are sampled separately and left off.
    tracesSampleRate: 0,
    sendDefaultPii: false,
  })
}

// Lets Sentry tie client-side navigations to error/perf events.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart
