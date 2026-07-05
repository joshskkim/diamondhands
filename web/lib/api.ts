import { queryOptions } from '@tanstack/react-query'
import type {
  AccuracyResponse,
  TrackRecord,
  BestPlay,
  BoomPick,
  GameOdds,
  GameProjections,
  HitRate,
  LineShop,
  ModelPickResult,
  MostLikely,
  PitcherSkillSplit,
  PitchTypeLeaderboardEntry,
  PitchTypeRef,
  PlayerDetail,
  PlayerResults,
  PlayerSpray,
  PropBoard,
  RecentStat,
  TodayGame,
} from './types'

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080'

export class ApiError extends Error {
  readonly status: number
  readonly path: string

  constructor(status: number, path: string) {
    super(`API error ${status}: ${path}`)
    this.name = 'ApiError'
    this.status = status
    this.path = path
  }
}

async function apiGet<T>(path: string): Promise<T> {
  // credentials:'include' so the session cookie rides along (no-op for server fetches).
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' })
  if (!res.ok) throw new ApiError(res.status, path)
  return res.json() as Promise<T>
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new ApiError(res.status, path)
  return (res.status === 204 ? undefined : await res.json()) as T
}

// ── Ask Diamond (AI natural-language query, SSE) ──────────────────────────────

/** A navigable result row: a friendly label + an in-app route to push to. */
export type AskLink = { label: string; href: string }

/** One event off the /api/ask stream: live tool-call status, links, the answer, sources, or error. */
export type AskEvent =
  | { type: 'status'; tool: string; label: string }
  | { type: 'links'; links: AskLink[] }
  | { type: 'answer'; text: string }
  | { type: 'sources'; tools: string[] }
  | { type: 'error'; message: string }

/** Parse one SSE record ("event: x\ndata: {...}") into an {@link AskEvent}. */
function parseAskEvent(record: string): AskEvent | null {
  let event = 'message'
  let data = ''
  for (const line of record.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  try {
    const payload = JSON.parse(data) as Record<string, unknown>
    switch (event) {
      case 'status':
        return { type: 'status', tool: String(payload.tool), label: String(payload.label) }
      case 'links':
        return { type: 'links', links: (payload.links as AskLink[]) ?? [] }
      case 'answer':
        return { type: 'answer', text: String(payload.text) }
      case 'sources':
        return { type: 'sources', tools: (payload.tools as string[]) ?? [] }
      case 'error':
        return { type: 'error', message: String(payload.message) }
      default:
        return null
    }
  } catch {
    return null
  }
}

/**
 * Stream an answer from the AI assistant. POSTs the question and reads the SSE response,
 * invoking {@link onEvent} for each status/answer/sources/error event as it arrives.
 */
export async function askDiamond(
  question: string,
  onEvent: (event: AskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/ask`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch {
    onEvent({ type: 'error', message: 'Could not reach the server.' })
    return
  }
  if (res.status === 503) {
    onEvent({ type: 'error', message: 'The AI assistant is not enabled on this server.' })
    return
  }
  if (!res.ok || !res.body) {
    onEvent({ type: 'error', message: `Request failed (${res.status}).` })
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const record = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const parsed = parseAskEvent(record)
      if (parsed) onEvent(parsed)
    }
  }
}

// ── Diamond Analyst (stateful agent) ───────────────────────────────────────────

/** A proposed write the user must confirm (the signed token replays the exact action). */
export type AgentConfirm = { token: string; action: string; summary: string }

/** One event off the /api/agent stream — adds debate `role` turns + `confirm` proposals. */
export type AgentEvent =
  | { type: 'thread'; threadId: number }
  | { type: 'status'; tool: string; label: string }
  | { type: 'role'; role: string; text: string }
  | { type: 'links'; links: AskLink[] }
  | { type: 'confirm'; confirm: AgentConfirm }
  | { type: 'answer'; text: string }
  | { type: 'sources'; tools: string[] }
  | { type: 'error'; message: string }

function parseAgentEvent(record: string): AgentEvent | null {
  let event = 'message'
  let data = ''
  for (const line of record.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  try {
    const payload = JSON.parse(data) as Record<string, unknown>
    switch (event) {
      case 'thread':
        return { type: 'thread', threadId: Number(payload.threadId) }
      case 'status':
        return { type: 'status', tool: String(payload.tool), label: String(payload.label) }
      case 'role':
        return { type: 'role', role: String(payload.role), text: String(payload.text) }
      case 'links':
        return { type: 'links', links: (payload.links as AskLink[]) ?? [] }
      case 'confirm':
        return {
          type: 'confirm',
          confirm: {
            token: String(payload.token),
            action: String(payload.action),
            summary: String(payload.summary),
          },
        }
      case 'answer':
        return { type: 'answer', text: String(payload.text) }
      case 'sources':
        return { type: 'sources', tools: (payload.tools as string[]) ?? [] }
      case 'error':
        return { type: 'error', message: String(payload.message) }
      default:
        return null
    }
  } catch {
    return null
  }
}

/**
 * Stream an answer from the authenticated Diamond Analyst. Same SSE shape as {@link askDiamond}
 * plus bull/skeptic/judge `role` turns and `confirm` proposals. Requires a signed-in session
 * (401 when not). Confirm a proposal with {@link confirmAction}.
 */
export async function askAgent(
  question: string,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
  threadId?: number | null,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/agent`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ question, threadId: threadId ?? null }),
      signal,
    })
  } catch {
    onEvent({ type: 'error', message: 'Could not reach the server.' })
    return
  }
  if (res.status === 401) {
    onEvent({ type: 'error', message: 'Sign in to use the Diamond Analyst.' })
    return
  }
  if (res.status === 503) {
    onEvent({ type: 'error', message: 'The AI assistant is not enabled on this server.' })
    return
  }
  if (!res.ok || !res.body) {
    onEvent({ type: 'error', message: `Request failed (${res.status}).` })
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const record = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const parsed = parseAgentEvent(record)
      if (parsed) onEvent(parsed)
    }
  }
}

/** Execute a confirmed write action; returns the server's human-readable result. */
export async function confirmAction(token: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/agent/confirm`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) throw new Error(`Confirm failed (${res.status}).`)
  const payload = (await res.json()) as { result?: string }
  return payload.result ?? 'Done.'
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export type AuthUser = { id: number; email: string; handle: string; pro: boolean }

/** Current user, or null when not signed in (API returns 401). */
export async function fetchMe(): Promise<AuthUser | null> {
  const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
  if (res.status === 401) return null
  if (!res.ok) throw new ApiError(res.status, '/api/auth/me')
  return res.json() as Promise<AuthUser>
}

export function signUp(input: {
  email: string
  handle: string
  password: string
}): Promise<AuthUser> {
  return apiPost<AuthUser>('/api/auth/signup', input)
}

export function signIn(input: { email: string; password: string }): Promise<AuthUser> {
  return apiPost<AuthUser>('/api/auth/signin', input)
}

export function signOut(): Promise<void> {
  return apiPost<void>('/api/auth/signout', {})
}

// ── Billing (Stripe Checkout + Customer Portal) ───────────────────────────────

/** Start a Pro subscription Checkout; returns the Stripe-hosted URL to redirect to. */
export function createCheckout(interval: 'monthly' | 'annual'): Promise<{ url: string }> {
  return apiPost<{ url: string }>('/api/billing/checkout', { interval })
}

/** Open the Stripe Customer Portal (manage/cancel); returns the URL to redirect to. */
export function createPortal(): Promise<{ url: string }> {
  return apiPost<{ url: string }>('/api/billing/portal', {})
}

// ── Fetchers (usable from Server Components and queryFn) ─────────────────────

export function fetchTodayGames(): Promise<TodayGame[]> {
  return apiGet<TodayGame[]>('/api/games/today')
}

export function fetchGameProjections(gameId: number): Promise<GameProjections> {
  return apiGet<GameProjections>(`/api/games/${gameId}/projections`)
}

export function fetchPlayer(playerId: number): Promise<PlayerDetail> {
  return apiGet<PlayerDetail>(`/api/players/${playerId}`)
}

export function fetchPlayerRecentStats(
  playerId: number,
  limit = 20,
): Promise<RecentStat[]> {
  const safeLimit = Math.min(Math.max(limit, 1), 100)
  return apiGet<RecentStat[]>(
    `/api/players/${playerId}/recent?limit=${safeLimit}`,
  )
}

export function searchPlayers(name: string, limit = 8): Promise<PlayerDetail[]> {
  const params = new URLSearchParams({ name, limit: String(limit) })
  return apiGet<PlayerDetail[]>(`/api/players/search?${params}`)
}

export function fetchGameOdds(gameId: number): Promise<GameOdds> {
  return apiGet<GameOdds>(`/api/games/${gameId}/odds`)
}

export function fetchPitcherSkill(pitcherId: number): Promise<PitcherSkillSplit[]> {
  return apiGet<PitcherSkillSplit[]>(`/api/pitchers/${pitcherId}/skill`)
}

export function fetchBestPlays(date?: string, limit = 50): Promise<BestPlay[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (date) params.set('date', date)
  return apiGet<BestPlay[]>(`/api/odds/best?${params}`)
}

/** The Lotto of the Day HR boom pick, or null when none qualifies (API returns 204). */
export async function fetchLotto(date?: string): Promise<BoomPick | null> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  const res = await fetch(`${API_BASE}/api/lotto${qs ? `?${qs}` : ''}`, {
    credentials: 'include',
  })
  if (res.status === 204) return null
  if (!res.ok) throw new ApiError(res.status, '/api/lotto')
  return res.json() as Promise<BoomPick>
}

export function fetchHitRates(date?: string): Promise<HitRate[]> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<HitRate[]>(`/api/odds/hit-rates${qs ? `?${qs}` : ''}`)
}

export function fetchLineShop(date?: string): Promise<LineShop[]> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<LineShop[]>(`/api/odds/line-shop${qs ? `?${qs}` : ''}`)
}

export function fetchPitchTypes(): Promise<PitchTypeRef[]> {
  return apiGet<PitchTypeRef[]>('/api/leaderboards/pitch-types')
}

export function fetchPlayerSpray(playerId: number, season?: number): Promise<PlayerSpray> {
  const params = new URLSearchParams()
  if (season) params.set('season', String(season))
  const qs = params.toString()
  return apiGet<PlayerSpray>(`/api/players/${playerId}/spray${qs ? `?${qs}` : ''}`)
}

export function fetchPropBoard(date?: string): Promise<PropBoard> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<PropBoard>(`/api/props/board${qs ? `?${qs}` : ''}`)
}

export function fetchModelPicks(date?: string): Promise<ModelPickResult[]> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<ModelPickResult[]>(`/api/model-picks${qs ? `?${qs}` : ''}`)
}

/** Identity of a pick on the live board, matching the server's reconcile PickKey. */
export interface PickKey {
  gameId: number
  market: string
  side: string
  playerId: number | null
}

/**
 * Tell the server which picks the live board is currently showing so it can record promptly
 * which earlier picks a better late play has displaced (and re-promote any that returned),
 * without waiting for the record-picks cron. boardLoaded=false (odds unavailable) is a no-op.
 */
export function reconcileModelPicks(
  activeKeys: PickKey[],
  boardLoaded: boolean,
  date?: string,
): Promise<void> {
  return apiPost<void>('/api/model-picks/reconcile', { date, activeKeys, boardLoaded })
}

export function fetchPlayerResults(date?: string): Promise<PlayerResults> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<PlayerResults>(`/api/results/players${qs ? `?${qs}` : ''}`)
}

export function fetchLivePlayerResults(date?: string): Promise<PlayerResults> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<PlayerResults>(`/api/results/players/live${qs ? `?${qs}` : ''}`)
}

export function fetchMostLikely(date?: string): Promise<MostLikely> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  return apiGet<MostLikely>(`/api/most-likely${qs ? `?${qs}` : ''}`)
}

export function fetchAccuracy(days = 30): Promise<AccuracyResponse> {
  const safeDays = Math.min(Math.max(days, 7), 180)
  return apiGet<AccuracyResponse>(`/api/accuracy?days=${safeDays}`)
}

export function fetchTrackRecord(days = 60): Promise<TrackRecord> {
  // days is clamped server-side too; a large value (All) yields the full history.
  return apiGet<TrackRecord>(`/api/track-record?days=${Math.max(days, 1)}`)
}

export function fetchPitchTypeLeaderboard(
  pitch: string,
  date?: string,
  limit = 20,
): Promise<PitchTypeLeaderboardEntry[]> {
  const params = new URLSearchParams({ pitch, limit: String(limit) })
  if (date) params.set('date', date)
  return apiGet<PitchTypeLeaderboardEntry[]>(`/api/leaderboards/pitch-type?${params}`)
}

// ── Personal Tracker ──────────────────────────────────────────────────────────

export interface TrackerEntry {
  id: number
  source: 'agent' | 'personal'
  slateDate: string
  gameId: number
  market: string
  side: string
  line: number | null
  playerId: number | null
  playerName: string | null
  priceAmerican: number | null
  book: string | null
  stakeUnits: number | null
  confidence: number | null
  modelProb: number | null
  fairProb: number | null
  edge: number | null
  won: boolean | null
  resultValue: number | null
  clv: number | null
  scored: boolean
  status: string
}

export interface TrackerSummary {
  picks: number
  wins: number
  losses: number
  pushes: number
  units: number
  roiPct: number
  clvN: number | null
  clvRate: number | null
  avgClv: number | null
}

export interface TrackerResponse {
  summary: TrackerSummary
  entries: TrackerEntry[]
}

export type TailRequest = {
  gameId: number
  market: string
  side: string
  line: number | null
  playerId: number | null
  playerName: string | null
  priceAmerican: number
  book: string | null
  modelProb: number
  fairProb: number
  confidence?: number | null
}

export type TailResult = { stakeUnits: number | null; alreadyTracked: boolean; message: string }

/** The signed-in user's tracked picks + logged bets, graded with ROI/CLV. */
export function fetchTracker(): Promise<TrackerResponse> {
  return apiGet<TrackerResponse>('/api/tracker')
}

/** Tail a board pick into the user's tracker (server computes the Kelly stake). */
export function tailPick(req: TailRequest): Promise<TailResult> {
  return apiPost<TailResult>('/api/tracker/tail', req)
}

/** @deprecated Prefer named fetchers; kept for existing imports. */
export const api = {
  todayGames: fetchTodayGames,
  gameProjections: fetchGameProjections,
  recentStats: fetchPlayerRecentStats,
}

// ── TanStack Query keys ───────────────────────────────────────────────────────

export const queryKeys = {
  games: {
    all: ['games'] as const,
    today: () => [...queryKeys.games.all, 'today'] as const,
    projections: (gameId: number) =>
      ['game', 'projections', gameId] as const,
    odds: (gameId: number) => ['game', 'odds', gameId] as const,
  },
  odds: {
    best: (date?: string) => ['odds', 'best', date ?? 'today'] as const,
    hitRates: (date?: string) => ['odds', 'hit-rates', date ?? 'today'] as const,
    lineShop: (date?: string) => ['odds', 'line-shop', date ?? 'today'] as const,
  },
  lotto: (date?: string) => ['lotto', date ?? 'today'] as const,
  mostLikely: (date?: string) => ['most-likely', date ?? 'today'] as const,
  modelPicks: (date?: string) => ['model-picks', date ?? 'today'] as const,
  tracker: () => ['tracker'] as const,
  propBoard: (date?: string) => ['prop-board', date ?? 'today'] as const,
  playerResults: (date?: string) => ['player-results', date ?? 'today'] as const,
  livePlayerResults: (date?: string) => ['player-results', 'live', date ?? 'today'] as const,
  players: {
    detail: (playerId: number) => ['player', 'detail', playerId] as const,
    recent: (playerId: number, limit = 20) =>
      ['player', 'recent', playerId, limit] as const,
    spray: (playerId: number, season?: number) =>
      ['player', 'spray', playerId, season ?? 'current'] as const,
    search: (name: string) => ['player', 'search', name] as const,
  },
  pitchers: {
    skill: (pitcherId: number) => ['pitcher', 'skill', pitcherId] as const,
  },
  leaderboards: {
    pitchTypes: () => ['leaderboards', 'pitch-types'] as const,
    pitchType: (pitch: string, date?: string, limit = 20) =>
      ['leaderboards', 'pitch-type', pitch, date ?? 'today', limit] as const,
  },
  accuracy: {
    trend: (days: number) => ['accuracy', 'trend', days] as const,
  },
  trackRecord: (days: number) => ['track-record', days] as const,
}

// ── Query options (use with useQuery / prefetchQuery) ─────────────────────────

export function todayGamesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.games.today(),
    queryFn: fetchTodayGames,
    // The slate updates through the day as the server re-projects games (lineups post on
    // the ~30-min cron). Poll so the home board — and the "X/Y projected" badge — climb on
    // their own without a manual reload. Cheap: one cached endpoint, deduped by key.
    refetchInterval: 5 * 60 * 1000,
  })
}

export function gameProjectionsQueryOptions(gameId: number) {
  return queryOptions({
    queryKey: queryKeys.games.projections(gameId),
    queryFn: () => fetchGameProjections(gameId),
  })
}

export function gameOddsQueryOptions(gameId: number) {
  return queryOptions({
    queryKey: queryKeys.games.odds(gameId),
    queryFn: () => fetchGameOdds(gameId),
  })
}

export function pitcherSkillQueryOptions(pitcherId: number) {
  return queryOptions({
    queryKey: queryKeys.pitchers.skill(pitcherId),
    queryFn: () => fetchPitcherSkill(pitcherId),
    enabled: pitcherId > 0,
  })
}

export function bestPlaysQueryOptions(date?: string, limit = 50) {
  return queryOptions({
    queryKey: queryKeys.odds.best(date),
    queryFn: () => fetchBestPlays(date, limit),
  })
}

export function lottoQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.lotto(date),
    queryFn: () => fetchLotto(date),
  })
}

export function hitRatesQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.odds.hitRates(date),
    queryFn: () => fetchHitRates(date),
  })
}

export function lineShopQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.odds.lineShop(date),
    queryFn: () => fetchLineShop(date),
  })
}

export function playerDetailQueryOptions(playerId: number) {
  return queryOptions({
    queryKey: queryKeys.players.detail(playerId),
    queryFn: () => fetchPlayer(playerId),
  })
}

export function playerRecentStatsQueryOptions(playerId: number, limit = 20) {
  return queryOptions({
    queryKey: queryKeys.players.recent(playerId, limit),
    queryFn: () => fetchPlayerRecentStats(playerId, limit),
  })
}

export function pitchTypesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.leaderboards.pitchTypes(),
    queryFn: fetchPitchTypes,
  })
}

export function playerSprayQueryOptions(playerId: number, season?: number) {
  return queryOptions({
    queryKey: queryKeys.players.spray(playerId, season),
    queryFn: () => fetchPlayerSpray(playerId, season),
    enabled: playerId > 0,
  })
}

export function playerSearchQueryOptions(name: string) {
  const trimmed = name.trim()
  return queryOptions({
    queryKey: queryKeys.players.search(trimmed.toLowerCase()),
    queryFn: () => searchPlayers(trimmed),
    // Only fire once there's something worth matching; keep prior results on
    // screen while the next keystroke's query resolves (no empty flash).
    enabled: trimmed.length >= 2,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  })
}

export function propBoardQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.propBoard(date),
    queryFn: () => fetchPropBoard(date),
  })
}

export function modelPicksQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.modelPicks(date),
    queryFn: () => fetchModelPicks(date),
  })
}

export function playerResultsQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.playerResults(date),
    queryFn: () => fetchPlayerResults(date),
  })
}

/** Live in-progress player counts. The caller gates polling (enabled/refetchInterval) on
 *  whether any game is actually live, so an idle slate pays nothing. */
export function livePlayerResultsQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.livePlayerResults(date),
    queryFn: () => fetchLivePlayerResults(date),
  })
}

export function mostLikelyQueryOptions(date?: string) {
  return queryOptions({
    queryKey: queryKeys.mostLikely(date),
    queryFn: () => fetchMostLikely(date),
  })
}

export function accuracyQueryOptions(days = 30) {
  return queryOptions({
    queryKey: queryKeys.accuracy.trend(days),
    queryFn: () => fetchAccuracy(days),
  })
}

export function trackRecordQueryOptions(days = 60) {
  return queryOptions({
    queryKey: queryKeys.trackRecord(days),
    queryFn: () => fetchTrackRecord(days),
  })
}

export function pitchTypeLeaderboardQueryOptions(
  pitch: string,
  date?: string,
  limit = 20,
) {
  return queryOptions({
    queryKey: queryKeys.leaderboards.pitchType(pitch, date, limit),
    queryFn: () => fetchPitchTypeLeaderboard(pitch, date, limit),
    enabled: Boolean(pitch),
  })
}
