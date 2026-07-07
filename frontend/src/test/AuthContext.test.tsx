import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAuth } from '../context/AuthContext'
import { AuthProvider } from '../context/AuthProvider'

vi.mock('../api/endpoints', () => ({
  getNotificationCount: vi.fn().mockResolvedValue({ count: 5 }),
}))

beforeEach(() => {
  localStorage.clear()
})

describe('AuthContext', () => {
  it('defaults to Comptable when localStorage is empty', () => {
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    expect(result.current.role).toBe('Comptable')
  })

  it('rehydrates role from localStorage on mount', () => {
    localStorage.setItem('biat_role', 'Direction')
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    expect(result.current.role).toBe('Direction')
  })

  it('persists role to localStorage on change', () => {
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    act(() => result.current.setRole('Chef de Projet'))
    expect(localStorage.getItem('biat_role')).toBe('Chef de Projet')
    expect(result.current.role).toBe('Chef de Projet')
  })

  it('maps Comptable role to correct name and initials', () => {
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    expect(result.current.name).toBe('Baya C.')
    expect(result.current.initials).toBe('BC')
  })

  it('maps Direction role to correct name', () => {
    localStorage.setItem('biat_role', 'Direction')
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    expect(result.current.name).toBe('Directeur')
  })

  it('maps Chef de Projet role to correct name', () => {
    localStorage.setItem('biat_role', 'Chef de Projet')
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    expect(result.current.name).toBe('Karim B.')
  })

  it('fetches notifCount from API on mount when authenticated', async () => {
    localStorage.setItem('biat_token', 'test-token')
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => {})
    expect(result.current.notifCount).toBe(5)
  })
})
