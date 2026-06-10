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
