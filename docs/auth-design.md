# Auth design — users & authentication for Diamond

> Status: the **MVP credential layer (Phase 1–2)** is being implemented (email+password,
> httpOnly-cookie sessions). Everything beyond it — picks/leaderboard, payments, OAuth — remains
> design only and is captured here so the foundation doesn't paint us into a corner.

## Why
The app today is fully open and read-only. There is no concept of a user. We want accounts so a
visitor can, per the existing `/signin` copy:

- **save picks**,
- **track their board**, and
- **sync across devices**.

That's the near-term driver. Auth is in service of *per-user persisted state*, not of locking down
the existing stats — the projection/odds data should stay publicly readable.

**Roadmap context (informs the design, not yet scoped):** beyond saving picks, the plan includes
user-facing features and a **leaderboard**, and possibly **payments** (premium vs. free tiers) with
the **sensitive info / PII** that implies. These don't change the MVP, but they shape every
decision below — see "Roadmap impact" before committing to an approach.

## Where we're starting from
- **Web** (`web/`): Next.js 16 (App Router), TanStack Query. `web/lib/api.ts` issues plain
  unauthenticated `GET`s against `NEXT_PUBLIC_API_URL`; no token/header/session handling anywhere.
  No auth libraries installed.
- **API** (`api/`): Spring Boot 3.3.6 / Java 21. All controllers are read-only `GET` data endpoints.
  No `spring-boot-starter-security`, no JWT/OAuth deps. `CorsConfig` allows only `GET`/`OPTIONS`
  from `http://localhost:3000`.
- **DB**: Postgres via Flyway, migrations V1–V19. No `users`/`accounts`/auth tables exist.
- **Caveat** (`web/AGENTS.md`): this is a *non-standard* Next.js 16 — APIs and conventions may
  differ from upstream. Read `node_modules/next/dist/docs/` before writing Next-specific code. This
  directly shapes the recommendation below.

## The three concerns to keep decoupled
Once a leaderboard, payments, and PII are in play, "auth" is really three separable concerns. Keep
them apart and each later addition stays contained:

- **Identity** — *who is this?* Login, password (later OAuth/MFA), sessions. The MVP.
- **Entitlement** — *what may they access?* Free vs. premium. Owned by billing (Stripe) and synced
  to our DB; enforced **server-side** on the API. Out of MVP scope, but nothing should block it.
- **Profile / picks / leaderboard** — *their app data.* Keyed by a stable internal `users.id`, never
  by the auth mechanism. Needs a public **`handle`** distinct from email so leaderboards never leak
  PII.

Everything outside Identity references only `users.id`. That single rule is what makes adding
Stripe/premium later — or even swapping the credential layer for a managed provider later — a
contained change instead of a rewrite.

## Recommendation: self-hosted email + password, httpOnly-cookie JWT sessions
Own auth in the Spring API against the existing Postgres, with the session carried in a secure
cookie rather than a token in JS — and treat **identity as a thin, swappable layer behind
`users.id`** (see above).

**Why self-host now, given payments are "likely, but not soon":**
- A free MVP needs only email + password; a managed provider's cost/complexity isn't justified yet.
- The decoupling above means we are **not locked in** — if/when payments make managed-grade security
  (MFA, account-takeover protection, offloaded password reset) worth it, we migrate the credential
  layer alone, not the data model.
- **Revisit trigger:** when payments become concrete, or we want OAuth/MFA, re-evaluate a managed
  provider (used framework-agnostically — see the alternative below).

**Why this over a managed provider (Clerk / Auth0 / Supabase Auth):**
- **Fits the stack we already run.** Spring Boot + Postgres + Flyway are here; adding a `users`
  table and `spring-boot-starter-security` introduces no new infrastructure and no vendor/cost.
- **Avoids depending on a provider's Next.js SDK.** The big selling point of managed providers is
  their frontend SDK (drop-in `<SignIn/>`, middleware-based route protection). Given the
  non-standard Next 16 here, that middleware/SDK layer is exactly the part most likely to break or
  behave unexpectedly. Hand-rolled forms + a cookie talk to our own API and sidestep that risk.
- **It doesn't even save backend work.** With a managed provider the Spring API would still have to
  verify the provider's JWTs (configure a resource server against their JWKS) and map them to local
  user rows. We'd own most of the backend either way.

**Why httpOnly cookies (not `localStorage` tokens):** a session JWT set as an `HttpOnly`, `Secure`,
`SameSite=Lax` cookie can't be read by injected JS, which removes the standard XSS token-theft
vector. The Next app never sees the token; it learns who the user is by calling `GET /api/auth/me`
with `credentials: 'include'`.

### What the alternative buys you (and its cost)
A managed provider (Clerk / Supabase Auth / WorkOS) is the right call if priorities shift toward
**fast OAuth/social login**, **offloaded password reset & email verification, MFA, and
account-takeover protection**, and minimal auth code to maintain — the safer posture for a paid
product holding PII. The cost is an external dependency, a bill past the free tier, and the Next-SDK
fragility noted above. If we go this route, **use the provider framework-agnostically** — its plain
JS/REST client + JWKS verification on the Spring side — and avoid its Next.js middleware/SDK, which
is the part most exposed to this non-standard Next 16.

## Roadmap impact (leaderboard, payments, PII)
Not built in the MVP, but these are why the decoupling above matters:

**Leaderboard.** Display a public `handle`, never the email. Scoring users' saved picks against real
outcomes is the *same problem the model already solves* — reuse the existing accuracy/backtest
machinery (`backtest_*` tables, `AccuracyService`, Brier + run-total scoring) to rank "users vs. the
model / each other." A user's pick history lives in `user_picks` (deferred until the board/pick
shape is designed).

**Payments.** Use **Stripe Checkout + Customer Portal** — we never store card data, which keeps us
in the lightest PCI tier (SAQ A). Persist only an `entitlements`/`subscriptions` row keyed by
`users.id`, updated by **signature-verified, idempotent** Stripe webhooks
(`checkout.session.completed`, `customer.subscription.updated|deleted`). The app reads tier from our
own DB (fast, cacheable), and **gates premium features server-side on the API** — UI gating alone is
never authoritative.

**Sensitive info / PII.** Store the minimum: email, `handle`, the bcrypt `password_hash`, and later
a Stripe customer id (an opaque token, not card data). TLS in transit; secrets (the JWT signing key,
Stripe keys) come from env/secrets management, never source — note the dev DB creds `diamond/diamond`
in compose must not ship to prod. Once accounts + payments exist, add an **account-deletion cascade**
and a privacy policy (GDPR/CCPA) so a user can be fully erased.

## Phased rollout
**Phase 1 — schema (`db/migrations/V21__users.sql`)** — *MVP, building now*
- `users (id, email UNIQUE, handle UNIQUE, password_hash, created_at)`.

**Phase 2 — API** — *MVP, building now*
- Add `spring-boot-starter-security` + `spring-boot-starter-oauth2-resource-server` (Nimbus JOSE for
  symmetric-key JWT); `BCryptPasswordEncoder` for hashing.
- `AuthController`: `POST /api/auth/signup`, `POST /api/auth/signin`, `POST /api/auth/signout`,
  `GET /api/auth/me`.
- Session JWT (subject = `users.id`, `handle` claim) issued as an `HttpOnly` + `SameSite=Lax`
  (`Secure` in prod) cookie `diamond_session`.
- `SecurityFilterChain`: existing `GET /api/**` stay **public**; a custom `BearerTokenResolver`
  reads the cookie; stateless, CSRF disabled (mitigated by `SameSite` + locked CORS).
- `CorsConfig`: `allowCredentials(true)` and permit `POST`.

**Phase 3 — web** — *MVP, building now*
- Real form at `web/app/signin/page.tsx` (sign-up / sign-in).
- Auth context (`web/components/auth-provider.tsx`) exposing the current user from `/api/auth/me`.
- `web/lib/api.ts`: send `credentials: 'include'`; add an `apiPost` helper.
- Sidebar (`web/components/app-sidebar.tsx`) shows the `handle` + sign-out when authenticated.

**Phase 4 — later (deferred, design only)**
- `user_picks` + save-pick endpoints; leaderboard scoring (reuse accuracy/backtest).
- Stripe + `entitlements` + server-side premium gating.
- Email verification + password reset, then OAuth (Google).

## Open questions to resolve later
- Exact `user_picks` shape — depends on what "a pick" / "the board" stores.
- Cookie domain/secure flags across local (`:3000` ↔ `:8080`) vs. a deployed setup.
- What's premium vs. free, and which reads (if any) become per-user (MVP default: none).
