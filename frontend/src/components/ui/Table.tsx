import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  className?: string
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  emptyMessage?: string
}

export default function Table<T>({ columns, rows, rowKey, onRowClick, emptyMessage = 'Aucun résultat' }: Props<T>) {
  return (
    <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ background: '#F0F4F9', borderBottom: '1px solid #D5E8F5' }}>
            {columns.map(col => (
              <th
                key={col.key}
                className={`text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide ${col.className ?? ''}`}
                style={{ color: '#5D6D7E' }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="text-center py-10 text-sm" style={{ color: '#5D6D7E' }}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={rowKey(row)}
                className={`transition-colors ${onRowClick ? 'cursor-pointer hover:bg-[#F0F4F9]' : ''}`}
                style={{ borderBottom: i < rows.length - 1 ? '1px solid #F0F4F9' : 'none' }}
                onClick={() => onRowClick?.(row)}
              >
                {columns.map(col => (
                  <td key={col.key} className={`px-4 py-3 ${col.className ?? ''}`}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
