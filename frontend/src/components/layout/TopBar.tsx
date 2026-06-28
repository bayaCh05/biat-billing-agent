import { useState, useEffect, useRef, useCallback } from 'react'
import { Search, Bell, AlertTriangle, X, CheckCheck } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { getNotificationList, markNotificationRead, markAllNotificationsRead } from '../../api/endpoints'
import type { NotificationItem } from '../../types'

interface Props {
  title: string
  badge?: string
}

const TYPE_ICON: Record<string, { label: string; color: string }> = {
  INVOICE_FLAGGED:   { label: 'Facture signalée',   color: '#C0391B' },
  INVOICE_ESCALATED: { label: 'Facture escaladée',  color: '#804CD7' },
  PAYMENT_OVERDUE:   { label: 'Paiement en retard', color: '#F0A600' },
  BUDGET_EXCEEDED:   { label: 'Budget dépassé',     color: '#E67E22' },
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'À l\'instant'
  if (m < 60) return `Il y a ${m} min`
  const h = Math.floor(m / 60)
  if (h < 24) return `Il y a ${h} h`
  return `Il y a ${Math.floor(h / 24)} j`
}

export default function TopBar({ title, badge }: Props) {
  const { notifCount, setNotifCount } = useAuth()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  const unreadCount = items.filter(n => !n.is_read).length

  const loadNotifs = useCallback(() => {
    setLoading(true)
    getNotificationList()
      .then(data => {
        setItems(data)
        setNotifCount?.(data.filter(n => !n.is_read).length)
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [setNotifCount])

  useEffect(() => { if (open) loadNotifs() }, [open, loadNotifs])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  async function handleMarkRead(id: string) {
    await markNotificationRead(id)
    setItems(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
    setNotifCount?.(prev => Math.max(0, (prev ?? 0) - 1))
  }

  async function handleMarkAll() {
    await markAllNotificationsRead()
    setItems(prev => prev.map(n => ({ ...n, is_read: true })))
    setNotifCount?.(0)
  }

  return (
    <header
      className="flex items-center gap-3 px-6 h-14 border-b shrink-0"
      style={{ background: '#fff', borderColor: '#D5E8F5' }}
    >
      <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>{title}</h1>

      {badge && (
        <span className="text-xs font-medium px-2.5 py-1 rounded-full" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
          ● {badge}
        </span>
      )}

      <div className="flex-1" />

      {/* Search */}
      <div className="relative">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#9BAFBF' }} />
        <input
          type="text"
          placeholder="Rechercher..."
          className="pl-8 pr-3 py-1.5 text-sm rounded-lg border outline-none w-52 transition-all"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E', background: '#F8FAFC' }}
          onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
          onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
        />
      </div>

      {/* Bell + dropdown panel */}
      <div className="relative" ref={panelRef}>
        <button
          onClick={() => setOpen(v => !v)}
          className="relative p-1.5 rounded-lg hover:bg-gray-50 transition-colors"
          title="Notifications"
        >
          <Bell size={18} style={{ color: open ? '#1A3A5C' : '#5D6D7E' }} />
          {notifCount > 0 && (
            <span
              className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-white flex items-center justify-center font-bold"
              style={{ background: '#C0391B', fontSize: 10 }}
            >
              {notifCount > 99 ? '99+' : notifCount}
            </span>
          )}
        </button>

        {open && (
          <div
            className="absolute right-0 top-10 z-50 shadow-xl rounded-xl border overflow-hidden"
            style={{ width: 360, background: '#fff', borderColor: '#D5E8F5' }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid #F0F4F9' }}>
              <p className="text-sm font-bold" style={{ color: '#1A3A5C' }}>
                Notifications
                {unreadCount > 0 && (
                  <span className="ml-1.5 px-1.5 py-0.5 rounded-full text-xs font-bold text-white" style={{ background: '#C0391B' }}>
                    {unreadCount}
                  </span>
                )}
              </p>
              <div className="flex items-center gap-2">
                {unreadCount > 0 && (
                  <button
                    onClick={handleMarkAll}
                    className="flex items-center gap-1 text-xs font-medium hover:underline"
                    style={{ color: '#1A3A5C' }}
                    title="Tout marquer comme lu"
                  >
                    <CheckCheck size={13} /> Tout lire
                  </button>
                )}
                <button onClick={() => setOpen(false)} className="opacity-50 hover:opacity-100 transition-opacity">
                  <X size={14} style={{ color: '#5D6D7E' }} />
                </button>
              </div>
            </div>

            {/* Body */}
            <div style={{ maxHeight: 400, overflowY: 'auto' }}>
              {loading ? (
                <p className="text-xs text-center py-8" style={{ color: '#5D6D7E' }}>Chargement…</p>
              ) : items.length === 0 ? (
                <p className="text-xs text-center py-8" style={{ color: '#5D6D7E' }}>Aucune notification.</p>
              ) : (
                items.map(item => {
                  const meta = TYPE_ICON[item.type] ?? { label: item.type, color: '#5D6D7E' }
                  return (
                    <div
                      key={item.id}
                      className="px-4 py-3 transition-colors"
                      style={{
                        borderBottom: '1px solid #F0F4F9',
                        background: item.is_read ? '#fff' : '#F5F9FF',
                      }}
                    >
                      <div className="flex items-start gap-2.5">
                        <AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: meta.color }} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-1">
                            <p className="text-xs font-semibold truncate" style={{ color: '#1A1A2E' }}>
                              {item.title}
                            </p>
                            {!item.is_read && (
                              <button
                                onClick={() => handleMarkRead(item.id)}
                                className="shrink-0 text-[10px] font-medium hover:underline"
                                style={{ color: '#5BA3C9' }}
                              >
                                Lu
                              </button>
                            )}
                          </div>
                          <p className="text-[11px] mt-0.5 line-clamp-2" style={{ color: '#5D6D7E' }}>
                            {item.body}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ background: '#FEF0EE', color: meta.color }}>
                              {meta.label}
                            </span>
                            <span className="text-[10px]" style={{ color: '#9BAFBF' }}>
                              {timeAgo(item.created_at)}
                            </span>
                            {!item.is_read && (
                              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: '#C0391B' }} />
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        )}
      </div>

    </header>
  )
}
