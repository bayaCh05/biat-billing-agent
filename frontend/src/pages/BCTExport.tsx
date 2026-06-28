import { useState, useEffect, useRef } from 'react'
import { Download, ShieldCheck, AlertTriangle } from 'lucide-react'
import type { BCTAgingItem } from '../types'
import { getBctAging, downloadBctReport, verifyBctReport, markRepatriated } from '../api/endpoints'
import { formatTND } from '../utils/formatters'
import PageSpinner from '../components/ui/PageSpinner'

const STATUS_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  OK:          { bg: '#E8F5F0', color: '#1D9E76', label: 'OK' },
  WARNING:     { bg: '#FFF8E8', color: '#F0A500', label: 'Avertissement' },
  OVERDUE:     { bg: '#FDECEA', color: '#C0391B', label: 'En retard' },
  REPATRIATED: { bg: '#EFF4FA', color: '#5BA3C9', label: 'Rapatrié' },
  PENDING:     { bg: '#F3F4F6', color: '#5D6D7E', label: 'En attente' },
}

const today = new Date()
const firstOfYear = `${today.getFullYear()}-01-01`
const todayStr = today.toISOString().slice(0, 10)

export default function BCTExport() {
  const [aging, setAging] = useState<BCTAgingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [fromDate, setFromDate] = useState(firstOfYear)
  const [toDate, setToDate] = useState(todayStr)
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)

  const csvRef = useRef<HTMLInputElement>(null)
  const sigRef = useRef<HTMLInputElement>(null)
  const [verifying, setVerifying] = useState(false)
  const [verifyResult, setVerifyResult] = useState<{ valid: boolean; message: string } | null>(null)

  const [repatiating, setRepatriating] = useState<string | null>(null)

  useEffect(() => {
    getBctAging()
      .then(setAging)
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  const handleDownload = async () => {
    setGenerating(true)
    setGenError(null)
    try {
      await downloadBctReport(fromDate, toDate)
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : 'Erreur lors de la génération')
    } finally {
      setGenerating(false)
    }
  }

  const handleVerify = async () => {
    const csvFile = csvRef.current?.files?.[0]
    const sigFile = sigRef.current?.files?.[0]
    if (!csvFile || !sigFile) {
      setVerifyResult({ valid: false, message: 'Veuillez sélectionner les deux fichiers.' })
      return
    }
    setVerifying(true)
    setVerifyResult(null)
    try {
      const result = await verifyBctReport(csvFile, sigFile)
      setVerifyResult(result)
    } catch (e: unknown) {
      setVerifyResult({ valid: false, message: e instanceof Error ? e.message : 'Erreur de vérification' })
    } finally {
      setVerifying(false)
    }
  }

  const handleMarkRepatriated = async (invoiceNum: string) => {
    setRepatriating(invoiceNum)
    try {
      await markRepatriated(invoiceNum)
      setAging(prev => prev.filter(i => i.invoice_number !== invoiceNum))
    } catch {
      // silently ignore for now
    } finally {
      setRepatriating(null)
    }
  }

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const overdueCount  = aging.filter(i => i.status === 'OVERDUE').length
  const warningCount  = aging.filter(i => i.status === 'WARNING').length

  return (
    <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', flex: 1 }}>
          🏦 Conformité BCT — Rapatriement Exports
        </h1>
        <span style={{ background: '#E8F5F0', color: '#1D9E76', borderRadius: 20, padding: '4px 12px', fontSize: 11, fontWeight: 600 }}>
          Circulaire 2025-13
        </span>
      </div>

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <SummaryCard label="Factures en alerte" value={aging.length} color="#5BA3C9" />
        <SummaryCard label="En retard (>120 j)" value={overdueCount} color="#C0391B" />
        <SummaryCard label="Avertissement (<20 j)" value={warningCount} color="#F0A500" />
      </div>

      {/* Generate report section */}
      <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 16 }}>
          Générer le rapport BCT (ZIP signé SHA-256)
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            <span style={{ color: '#5D6D7E', fontWeight: 500 }}>Du</span>
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              style={{ border: '1px solid #D5E8F5', borderRadius: 6, padding: '6px 10px', fontSize: 13 }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            <span style={{ color: '#5D6D7E', fontWeight: 500 }}>Au</span>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              style={{ border: '1px solid #D5E8F5', borderRadius: 6, padding: '6px 10px', fontSize: 13 }}
            />
          </label>
          <button
            onClick={handleDownload}
            disabled={generating}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: generating ? '#B0C4D8' : '#1A3A5C',
              color: '#fff', border: 'none', borderRadius: 8,
              padding: '8px 18px', fontSize: 13, fontWeight: 600,
              cursor: generating ? 'not-allowed' : 'pointer',
            }}
          >
            <Download size={14} />
            {generating ? 'Génération...' : 'Générer rapport BCT'}
          </button>
        </div>
        {genError && (
          <div style={{ marginTop: 10, color: '#C0391B', fontSize: 12 }}>{genError}</div>
        )}
      </div>

      {/* Verify integrity section */}
      <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 16 }}>
          Vérifier l'intégrité d'un rapport
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            <span style={{ color: '#5D6D7E', fontWeight: 500 }}>Fichier CSV</span>
            <input ref={csvRef} type="file" accept=".csv" style={{ fontSize: 12 }} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            <span style={{ color: '#5D6D7E', fontWeight: 500 }}>Signature JSON</span>
            <input ref={sigRef} type="file" accept=".json" style={{ fontSize: 12 }} />
          </label>
          <button
            onClick={handleVerify}
            disabled={verifying}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: verifying ? '#B0C4D8' : '#804CD7',
              color: '#fff', border: 'none', borderRadius: 8,
              padding: '8px 18px', fontSize: 13, fontWeight: 600,
              cursor: verifying ? 'not-allowed' : 'pointer',
            }}
          >
            <ShieldCheck size={14} />
            {verifying ? 'Vérification...' : 'Vérifier intégrité'}
          </button>
        </div>
        {verifyResult && (
          <div style={{
            marginTop: 12, padding: '10px 14px', borderRadius: 8, fontSize: 13,
            background: verifyResult.valid ? '#E8F5F0' : '#FDECEA',
            color: verifyResult.valid ? '#1D9E76' : '#C0391B',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            {verifyResult.valid
              ? <ShieldCheck size={14} />
              : <AlertTriangle size={14} />
            }
            {verifyResult.message}
          </div>
        )}
      </div>

      {/* Aging table */}
      <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 16 }}>
          Factures export en alerte BCT
        </div>
        {aging.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#1D9E76', padding: 32, fontSize: 14 }}>
            Toutes les factures export sont conformes.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#F0F4F9' }}>
                  {['N° Facture', 'Client', 'Devise', 'Montant TND', 'Date envoi', 'Échéance BCT', 'Jours restants/retard', 'Statut', 'Garantie', 'Action'].map(h => (
                    <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 600, color: '#1A3A5C', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {aging.map(item => {
                  const s = STATUS_STYLE[item.status] ?? STATUS_STYLE.PENDING
                  const daysAbs = Math.abs(item.days_remaining_or_overdue ?? 0)
                  const daysLabel = item.status === 'OVERDUE'
                    ? `+${daysAbs} j de retard`
                    : `${daysAbs} j restants`
                  return (
                    <tr key={item.invoice_number} style={{ borderBottom: '1px solid #F0F4F9' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600 }}>{item.invoice_number}</td>
                      <td style={{ padding: '10px 12px' }}>{item.client_name}</td>
                      <td style={{ padding: '10px 12px' }}>{item.currency}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 600 }}>{formatTND(item.amount_tnd)}</td>
                      <td style={{ padding: '10px 12px' }}>{item.shipment_date ?? '—'}</td>
                      <td style={{ padding: '10px 12px' }}>{item.repatriation_deadline ?? '—'}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: s.color }}>{daysLabel}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ background: s.bg, color: s.color, borderRadius: 12, padding: '3px 10px', fontSize: 11, fontWeight: 600 }}>
                          {s.label}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', fontSize: 11, color: '#5D6D7E' }}>
                        {item.payment_guarantee_type ?? 'STANDARD'}
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <button
                          onClick={() => handleMarkRepatriated(item.invoice_number)}
                          disabled={repatiating === item.invoice_number}
                          style={{
                            background: '#1D9E76', color: '#fff', border: 'none',
                            borderRadius: 6, padding: '4px 10px', fontSize: 11,
                            fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
                          }}
                        >
                          {repatiating === item.invoice_number ? '...' : 'Confirmer rapatriement'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{
      background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12,
      padding: '16px 20px', position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: color, borderRadius: '4px 0 0 4px' }} />
      <div style={{ fontSize: 12, color: '#5D6D7E', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: '#1A3A5C' }}>{value}</div>
    </div>
  )
}
