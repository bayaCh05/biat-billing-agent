import { describe, it, expect } from 'vitest'
import { formatTND, formatTNDCompact, formatDate, formatConfidence, formatVariance, confidenceColor } from '../utils/formatters'

describe('formatTND', () => {
  it('formats 0 with 3 decimals', () => {
    expect(formatTND(0)).toContain('TND')
  })

  it('returns — TND for null', () => {
    expect(formatTND(null)).toBe('— TND')
  })

  it('returns — TND for undefined', () => {
    expect(formatTND(undefined)).toBe('— TND')
  })

  it('respects custom decimal override', () => {
    const result = formatTND(1234, 0)
    expect(result).toContain('TND')
    expect(result).not.toContain(',')
  })

  it('includes TND suffix', () => {
    expect(formatTND(500)).toMatch(/TND$/)
  })
})

describe('formatTNDCompact', () => {
  it('shows M for millions', () => {
    expect(formatTNDCompact(2_500_000)).toContain('M TND')
  })

  it('shows K for thousands', () => {
    expect(formatTNDCompact(15_000)).toContain('K TND')
  })

  it('falls through to formatTND for small values', () => {
    expect(formatTNDCompact(42)).toContain('TND')
    expect(formatTNDCompact(42)).not.toContain('K')
    expect(formatTNDCompact(42)).not.toContain('M')
  })

  it('returns — TND for null', () => {
    expect(formatTNDCompact(null)).toBe('— TND')
  })
})

describe('formatDate', () => {
  it('returns — for null', () => {
    expect(formatDate(null)).toBe('—')
  })

  it('returns — for undefined', () => {
    expect(formatDate(undefined)).toBe('—')
  })

  it('formats a valid ISO date', () => {
    const result = formatDate('2026-06-15')
    expect(result).toMatch(/\d{2}\/\d{2}\/\d{4}/)
  })

  it('returns the raw string for an invalid date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

describe('formatConfidence', () => {
  it('converts 0.95 to 95%', () => {
    expect(formatConfidence(0.95)).toBe('95%')
  })

  it('rounds to nearest integer', () => {
    expect(formatConfidence(0.876)).toBe('88%')
  })
})

describe('formatVariance', () => {
  it('adds + sign for positive values', () => {
    expect(formatVariance(5.5)).toBe('+5.5%')
  })

  it('keeps − sign for negative values', () => {
    expect(formatVariance(-3.2)).toBe('-3.2%')
  })

  it('shows zero without sign', () => {
    expect(formatVariance(0)).toBe('0.0%')
  })
})

describe('confidenceColor', () => {
  it('returns green for high confidence', () => {
    expect(confidenceColor(0.9)).toBe('#1D9E76')
  })

  it('returns amber for medium confidence', () => {
    expect(confidenceColor(0.7)).toBe('#F0A600')
  })

  it('returns red for low confidence', () => {
    expect(confidenceColor(0.4)).toBe('#C0391B')
  })
})
