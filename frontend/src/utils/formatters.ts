/**
 * Format a number as Tunisian Dinar (TND).
 * Uses fr-TN locale with 3 decimal places (standard for TND).
 */
export function formatTND(amount: number | null | undefined, decimals = 3): string {
  if (amount == null) return '— TND'
  return `${amount.toLocaleString('fr-TN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })} TND`
}

/**
 * Format a number as TND with compact notation (e.g. 1 247K TND).
 */
export function formatTNDCompact(amount: number | null | undefined): string {
  if (amount == null) return '— TND'
  if (Math.abs(amount) >= 1_000_000) return `${(amount / 1_000_000).toFixed(2)}M TND`
  if (Math.abs(amount) >= 1_000) return `${(amount / 1_000).toFixed(0)}K TND`
  return formatTND(amount)
}

/**
 * Format a date string (ISO 8601) to DD/MM/YYYY.
 */
export function formatDate(date: string | null | undefined): string {
  if (!date) return '—'
  const d = new Date(date)
  if (isNaN(d.getTime())) return date
  return d.toLocaleDateString('fr-TN', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/**
 * Format a confidence score (0–1) as a percentage string.
 */
export function formatConfidence(conf: number): string {
  return `${Math.round(conf * 100)}%`
}

/**
 * Return a colour string based on confidence level.
 */
export function confidenceColor(conf: number): string {
  if (conf >= 0.85) return '#1D9E76'
  if (conf >= 0.60) return '#F0A600'
  return '#C0391B'
}

/**
 * Format a percentage variance with sign.
 */
export function formatVariance(pct: number): string {
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(1)}%`
}
