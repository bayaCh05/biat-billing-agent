import type { InvoiceStatus } from '../../types'

const STATUS_MAP: Record<string, { label: string; dot: string; bg: string; color: string }> = {
  RECEIVED:          { label: 'Reçue',       dot: '#5BA3C9', bg: '#E3F0F9', color: '#1A3A5C' },
  EXTRACTING:        { label: 'Extraction',  dot: '#5BA3C9', bg: '#E3F0F9', color: '#1A3A5C' },
  EXTRACTED:         { label: 'Extraite',    dot: '#5BA3C9', bg: '#E3F0F9', color: '#1A3A5C' },
  CLASSIFYING:       { label: 'Classif.',    dot: '#5BA3C9', bg: '#E3F0F9', color: '#1A3A5C' },
  CLASSIFIED:        { label: 'Classifiée',  dot: '#5BA3C9', bg: '#E3F0F9', color: '#1A3A5C' },
  VALIDATING:        { label: 'Validation',  dot: '#F0A600', bg: '#FFF8E8', color: '#B07800' },
  VALIDATED:         { label: 'Validée',     dot: '#1D9E76', bg: '#E8F5F0', color: '#0D6E52' },
  FLAGGED:           { label: 'Signalée',    dot: '#F0A600', bg: '#FFF8E8', color: '#B07800' },
  EXPORTING:         { label: 'Export',      dot: '#804CD7', bg: '#F0EBF9', color: '#5A30A0' },
  EXPORTED:          { label: 'Exportée',    dot: '#1D9E76', bg: '#E8F5F0', color: '#0D6E52' },
  JOURNALING:        { label: 'Journal',     dot: '#804CD7', bg: '#F0EBF9', color: '#5A30A0' },
  JOURNALED:         { label: 'Journalisée', dot: '#1D9E76', bg: '#E8F5F0', color: '#0D6E52' },
  PAID:              { label: 'Payée',       dot: '#1D9E76', bg: '#E8F5F0', color: '#0D6E52' },
  COLLECTED:         { label: 'Encaissée',   dot: '#1D9E76', bg: '#E8F5F0', color: '#0D6E52' },
  ERROR:             { label: 'Erreur',      dot: '#C0391B', bg: '#FDECEA', color: '#9A2415' },
  REJECTED:          { label: 'Rejetée',     dot: '#C0391B', bg: '#FDECEA', color: '#9A2415' },
  EXTRACTION_FAILED: { label: 'OCR échoué', dot: '#C0391B', bg: '#FDECEA', color: '#9A2415' },
  ESCALATED:         { label: 'Escaladée',  dot: '#804CD7', bg: '#F0EBF9', color: '#5A30A0' },
}

const DEFAULT = { label: '—', dot: '#5D6D7E', bg: '#F0F4F9', color: '#5D6D7E' }

interface Props {
  status: InvoiceStatus | string
}

export default function StatusChip({ status }: Props) {
  const s = STATUS_MAP[status] ?? DEFAULT
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.color }}
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: s.dot }} />
      {s.label}
    </span>
  )
}
