/** Format American odds for display: +150 / -110 / — when absent. */
export function formatAmerican(price: number | null | undefined): string {
  if (price == null) return '—'
  return price > 0 ? `+${price}` : `${price}`
}

/** American odds → decimal payout multiplier (stake included). */
export function americanToDecimal(price: number): number {
  return price > 0 ? 1 + price / 100 : 1 + 100 / Math.abs(price)
}

/** Implied win probability from American odds (includes the book's vig). */
export function impliedFromAmerican(price: number): number {
  return price > 0 ? 100 / (price + 100) : Math.abs(price) / (Math.abs(price) + 100)
}

/** Expected value per 1 unit staked, given a model win prob and American price. */
export function expectedValue(modelProb: number, price: number): number {
  return modelProb * americanToDecimal(price) - 1
}

/** Display label for a book key (e.g. "fanduel" → "FanDuel"). */
const BOOK_LABELS: Record<string, string> = {
  fanduel: 'FanDuel',
  draftkings: 'DraftKings',
  fanatics: 'Fanatics',
  betrivers: 'BetRivers',
  betmgm: 'BetMGM',
  bovada: 'Bovada',
  betonlineag: 'BetOnline',
  lowvig: 'LowVig',
  mybookieag: 'MyBookie',
  betus: 'BetUS',
}

export function bookLabel(book: string | null | undefined): string {
  if (!book) return ''
  return BOOK_LABELS[book] ?? book
}

/** Display label for a market key on the odds boards. */
export const MARKET_LABEL: Record<string, string> = {
  moneyline: 'Moneyline',
  run_line: 'Run line',
  total: 'Total',
  hit: 'Hit',
  hr: 'Home run',
  bb: 'Walks',
  tb: 'Total bases',
  hrr: 'H+R+RBI',
  pitcher_k: 'Strikeouts',
  pitcher_outs: 'Outs',
  pitcher_hits_allowed: 'Hits allowed',
  pitcher_earned_runs: 'Earned runs',
}

/** Player-prop markets by the side of the ball they belong to, in display order.
 *  Drives the game page's prop market selector. */
export const BATTER_PROP_MARKETS = ['hit', 'hr', 'tb', 'hrr', 'bb'] as const
export const PITCHER_PROP_MARKETS = [
  'pitcher_k',
  'pitcher_outs',
  'pitcher_hits_allowed',
  'pitcher_earned_runs',
] as const

/** "AWY @ HOM" → team abbr for a 'home'/'away' side token. */
export function teamForSide(matchup: string, side: string): string {
  const parts = matchup.split(' @ ')
  if (parts.length !== 2) return side
  return side === 'home' ? parts[1] : parts[0]
}
