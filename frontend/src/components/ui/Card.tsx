interface Props {
  className?: string
  children: React.ReactNode
}

export default function Card({ className = '', children }: Props) {
  return (
    <div
      className={`bg-white rounded-xl border p-5 shadow-sm ${className}`}
      style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}
    >
      {children}
    </div>
  )
}

export function KpiCard({ label, value, delta, sub }: {
  label: string; value: string | number; delta?: string; sub?: string
}) {
  const isPositive = delta?.startsWith('+')
  const isNegative = delta?.startsWith('-')
  return (
    <div
      className="bg-white rounded-xl border p-5 shadow-sm"
      style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}
    >
      <p className="text-xs font-medium mb-2" style={{ color: '#5D6D7E' }}>{label}</p>
      <p className="text-2xl font-bold" style={{ color: '#1A3A5C' }}>{value}</p>
      {delta && (
        <p className={`text-xs mt-1 font-medium ${isPositive ? 'text-[#1D9E76]' : isNegative ? 'text-[#C0391B]' : 'text-[#5D6D7E]'}`}>
          {delta}
        </p>
      )}
      {sub && <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>{sub}</p>}
    </div>
  )
}
