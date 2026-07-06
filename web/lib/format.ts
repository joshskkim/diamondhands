// Shared number formatters. One definition each — extend here, never redefine locally.

/** A probability/fraction as a percentage: 0.423 → "42.3%". Nullish → em dash. */
export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return (v * 100).toFixed(digits) + '%'
}

/** A signed number: 1.5 → "+1.5", -0.6 → "-0.6". Nullish → em dash. */
export function signed(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(digits)
}

/** A signed percentage from a fraction: 0.042 → "+4.2%". Nullish → em dash. */
export function signedPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return signed(v * 100, digits) + '%'
}
