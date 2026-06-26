import PageHeader from '../../components/ui/PageHeader'
import Card from '../../components/ui/Card'

type Access = 'full' | 'read' | 'none'

interface HabRow {
  feature: string
  admin: Access
  comptable: Access
  chef: Access
  direction: Access
}

const ROWS: HabRow[] = [
  { feature: 'Créer un utilisateur',          admin: 'full', comptable: 'none', chef: 'none',  direction: 'none' },
  { feature: 'Tableau des habilitations',      admin: 'full', comptable: 'none', chef: 'none',  direction: 'none' },
  { feature: 'Soumettre facture fournisseur',  admin: 'none', comptable: 'full', chef: 'none',  direction: 'none' },
  { feature: 'Valider facture',                admin: 'none', comptable: 'full', chef: 'none',  direction: 'none' },
  { feature: 'Générer écriture PCE',           admin: 'none', comptable: 'full', chef: 'none',  direction: 'none' },
  { feature: 'Créer immobilisation CAPEX',     admin: 'none', comptable: 'full', chef: 'none',  direction: 'none' },
  { feature: 'Grand Livre / Journal',          admin: 'none', comptable: 'full', chef: 'none',  direction: 'read' },
  { feature: 'Créer projet / charte',          admin: 'none', comptable: 'none', chef: 'full',  direction: 'none' },
  { feature: 'Gérer lignes budget',            admin: 'none', comptable: 'full', chef: 'full',  direction: 'none' },
  { feature: 'Valider phase',                  admin: 'none', comptable: 'none', chef: 'full',  direction: 'none' },
  { feature: 'Gérer livrables',                admin: 'none', comptable: 'none', chef: 'full',  direction: 'none' },
  { feature: 'Créer facture client',           admin: 'none', comptable: 'none', chef: 'full',  direction: 'none' },
  { feature: 'Feuille de route 2026',          admin: 'none', comptable: 'read', chef: 'full',  direction: 'read' },
  { feature: 'Tableau de bord financier',      admin: 'none', comptable: 'full', chef: 'full',  direction: 'read' },
  { feature: 'Dashboard Direction',            admin: 'none', comptable: 'none', chef: 'none',  direction: 'full' },
  { feature: 'Exporter écritures',             admin: 'none', comptable: 'full', chef: 'none',  direction: 'read' },
  { feature: 'Requêtes NL (SQL naturel)',      admin: 'none', comptable: 'full', chef: 'none',  direction: 'full' },
  { feature: 'Immobilisations (CAPEX)',        admin: 'none', comptable: 'full', chef: 'none',  direction: 'read' },
]

const BADGE: Record<Access, { label: string; bg: string; color: string }> = {
  full: { label: '✅ Complet',     bg: '#E8F5F0', color: '#0D6E52' },
  read: { label: '👁️ Lecture',    bg: '#EFF4FA', color: '#1A3A5C' },
  none: { label: '❌ Aucun',       bg: '#F0F4F9', color: '#9BAFBF' },
}

const COLS = [
  { key: 'admin' as const,    label: 'ADMIN',        color: '#C0391B' },
  { key: 'comptable' as const, label: 'COMPTABLE',    color: '#1A3A5C' },
  { key: 'chef' as const,     label: 'CHEF PROJET',   color: '#B07800' },
  { key: 'direction' as const, label: 'DIRECTION',     color: '#5A30A0' },
]

export default function HabilitationsPage() {
  return (
    <div>
      <PageHeader title="Tableau des habilitations" badge="Référentiel des droits d'accès" />

      <div className="p-6 space-y-5">
        <div className="grid grid-cols-4 gap-3">
          {COLS.map(c => (
            <div key={c.key} className="rounded-xl border p-4 text-center" style={{ borderColor: '#D5E8F5', background: '#fff' }}>
              <p className="text-xs font-bold tracking-widest" style={{ color: c.color }}>{c.label}</p>
              <p className="text-xl font-bold mt-1" style={{ color: '#1A3A5C' }}>
                {ROWS.filter(r => r[c.key] === 'full').length}
              </p>
              <p className="text-xs" style={{ color: '#5D6D7E' }}>droits complets</p>
            </div>
          ))}
        </div>

        <Card>
          <div className="flex items-center gap-4 mb-4 flex-wrap">
            {Object.entries(BADGE).map(([k, v]) => (
              <span key={k} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold" style={{ background: v.bg, color: v.color }}>
                {v.label}
              </span>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '2px solid #E2EBF3' }}>
                  <th className="text-left pb-3 pr-6 text-xs font-semibold" style={{ color: '#5D6D7E' }}>Fonctionnalité</th>
                  {COLS.map(c => (
                    <th key={c.key} className="text-center pb-3 px-3 text-xs font-bold tracking-wider" style={{ color: c.color }}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #F0F4F9' }}>
                    <td className="py-2.5 pr-6 font-medium" style={{ color: '#1A1A2E' }}>{row.feature}</td>
                    {COLS.map(c => {
                      const b = BADGE[row[c.key]]
                      return (
                        <td key={c.key} className="py-2.5 px-3 text-center">
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold" style={{ background: b.bg, color: b.color }}>
                            {b.label}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  )
}
