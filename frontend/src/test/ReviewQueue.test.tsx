import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ReviewQueue from '../pages/ReviewQueue'

// Stub auth context
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ role: 'Comptable', initials: 'BC', name: 'Baya C.' }),
}))

// Stub API calls
const mockApprove = vi.fn()
const mockReject = vi.fn()

vi.mock('../api/endpoints', () => ({
  getReviewQueue: vi.fn().mockResolvedValue([]),
  approveInvoice: (...args: unknown[]) => mockApprove(...args),
  rejectInvoice:  (...args: unknown[]) => mockReject(...args),
}))

// Stub mock data so the queue has one item
vi.mock('../data/mockInvoices', () => ({
  reviewQueueMock: [
    {
      id: 'inv-001',
      status: 'FLAGGED',
      direction: 'SUPPLIER',
      issuer_name: 'OOREDOO TUNISIE',
      invoice_number: 'OOR-2026-001',
      invoice_date: '2026-06-01',
      amount_ht: 8000,
      tva_rate: 19,
      tva_amount: 1520,
      amount_ttc: 9520,
      currency: 'TND',
      accounting_compte: '6260',
      accounting_label: 'Télécoms',
      extraction_method: 'LLM',
      flags: [{ flag_type: 'TOTAL_MISMATCH', severity: 'ERROR', field_name: 'amount_ttc', message: 'Écart détecté', resolved: false }],
      human_review_required: true,
      has_errors: true,
      received_at: new Date().toISOString(),
    },
  ],
}))

beforeEach(() => {
  mockApprove.mockResolvedValue({ id: 'inv-001', action: 'approved', new_status: 'VALIDATED' })
  mockReject.mockResolvedValue({ id: 'inv-001', action: 'rejected', new_status: 'REJECTED' })
})

describe('ReviewQueue', () => {
  it('renders the queue item', () => {
    render(<ReviewQueue />)
    expect(screen.getByText('OOREDOO TUNISIE')).toBeInTheDocument()
  })

  it('shows approve and reject buttons', () => {
    render(<ReviewQueue />)
    expect(screen.getByText('Approuver')).toBeInTheDocument()
    expect(screen.getByText('Rejeter')).toBeInTheDocument()
  })

  it('shows success toast after approve', async () => {
    render(<ReviewQueue />)
    fireEvent.click(screen.getByText('Approuver'))
    await waitFor(() =>
      expect(screen.getByText(/approuvée/i)).toBeInTheDocument()
    )
  })

  it('removes item from list after approve', async () => {
    render(<ReviewQueue />)
    fireEvent.click(screen.getByText('Approuver'))
    await waitFor(() =>
      expect(screen.queryByText('OOREDOO TUNISIE')).not.toBeInTheDocument()
    )
  })

  it('shows error toast when approve API call fails', async () => {
    mockApprove.mockRejectedValueOnce(new Error('Network error'))
    render(<ReviewQueue />)
    fireEvent.click(screen.getByText('Approuver'))
    await waitFor(() =>
      expect(screen.getByText(/Erreur réseau/i)).toBeInTheDocument()
    )
  })

  it('keeps item in list when approve fails', async () => {
    mockApprove.mockRejectedValueOnce(new Error('Network error'))
    render(<ReviewQueue />)
    fireEvent.click(screen.getByText('Approuver'))
    await waitFor(() =>
      expect(screen.getByText(/Erreur réseau/i)).toBeInTheDocument()
    )
    expect(screen.getByText('OOREDOO TUNISIE')).toBeInTheDocument()
  })

  it('shows "File vide" when queue is empty', async () => {
    render(<ReviewQueue />)
    fireEvent.click(screen.getByText('Approuver'))
    await waitFor(() =>
      expect(screen.getByText(/File vide/i)).toBeInTheDocument()
    )
  })
})
