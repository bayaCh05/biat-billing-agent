import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, CheckCheck, X, AlertTriangle, Clock, TrendingUp, FileText } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { getNotificationList, markNotificationRead, markAllNotificationsRead } from '../../api/endpoints'
import type { NotificationItem } from '../../types'

const TYPE_META: Record<string, { label: string; color: string; bg: string; Icon: typeof Bell }> = {
  INVOICE_FLAGGED:   { label: 'Facture signalée',   color: '#C0391B', bg: '#FEF0EE', Icon: AlertTriangle },
  INVOICE_ESCALATED: { label: 'Facture escaladée',  color: '#804CD7', bg: '#F3EDFF', Icon: AlertTriangle },
  PAYMENT_OVERDUE:   { label: 'Paiement en retard', color: '#F0A600', bg: '#FEF9E7', Icon: Clock },
  BUDGET_EXCEEDED:   { label: 'Budget dépassé',     color: '#E67E22', bg: '#FEF5EC', Icon: TrendingUp },
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return "À l'instant"
  if (m < 60) return `Il y a ${m} min`
  const h = Math.floor(m / 60)
  if (h < 24) return `Il y a ${h}h`
  const d = Math.floor(h / 24)
  if (d < 7) return `Il y a ${d}j`
  return new Date(iso).toLocaleDateString('fr-TN', { day: '2-digit', month: 'short' })
}

const MAX_VISIBLE = 10

export default function NotificationBell() {
  const { notifCount, setNotifCount } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(false)
  const [marking, setMarking] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  const unreadCount = items.filter(n => !n.is_read).length
  const visible = items.slice(0, MAX_VISIBLE)

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

  // Reload when the dropdown opens
  useEffect(() => {
    if (open) queueMicrotask(loadNotifs)
  }, [open, loadNotifs])

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  async function handleMarkRead(id: string) {
    await markNotificationRead(id)
    setItems(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
    setNotifCount?.(prev => Math.max(0, (prev ?? 0) - 1))
  }

  async function handleMarkAll() {
    setMarking(true)
    await markAllNotificationsRead()
    setItems(prev => prev.map(n => ({ ...n, is_read: true })))
    setNotifCount?.(0)
    setMarking(false)
  }

  return (
    <div className="relative" ref={panelRef}>

      {/* ── Bouton cloche ─────────────────────────────────────────────────── */}
      <button
        onClick={() => setOpen(v => !v)}
        className="relative p-1.5 rounded-lg transition-colors hover:bg-gray-50"
        aria-label="Notifications"
        aria-expanded={open}
        aria-haspopup="true"
      >
        <Bell
          size={18}
          style={{
            color: open ? '#1A3A5C' : '#5D6D7E',
            transition: 'color 0.15s',
          }}
        />
        {notifCount > 0 && (
          <span
            className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-white flex items-center justify-center font-bold"
            style={{ background: '#C0391B', fontSize: 10, lineHeight: 1 }}
          >
            {notifCount > 99 ? '99+' : notifCount}
          </span>
        )}
      </button>

      {/* ── Dropdown ──────────────────────────────────────────────────────── */}
      {open && (
        <div
          className="notif-dropdown absolute right-0 top-10 z-50 shadow-xl rounded-xl border overflow-hidden"
          style={{
            width: 'min(380px, calc(100vw - 1rem))',
            background: '#fff',
            borderColor: '#D5E8F5',
          }}
          role="dialog"
          aria-label="Panneau de notifications"
        >
          {/* En-tête */}
          <div
            className="flex items-center justify-between px-4 py-3"
            style={{ borderBottom: '1px solid #F0F4F9' }}
          >
            <div className="flex items-center gap-2">
              <p className="text-sm font-bold" style={{ color: '#1A3A5C' }}>Notifications</p>
              {unreadCount > 0 && (
                <span
                  className="px-1.5 py-0.5 rounded-full text-xs font-bold text-white"
                  style={{ background: '#C0391B' }}
                >
                  {unreadCount}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1">
              {unreadCount > 0 && (
                <button
                  onClick={handleMarkAll}
                  disabled={marking}
                  className="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md transition-colors hover:bg-gray-50 disabled:opacity-50"
                  style={{ color: '#1A3A5C' }}
                  title="Tout marquer comme lu"
                >
                  <CheckCheck size={12} />
                  <span className="hidden sm:inline">Tout marquer comme lu</span>
                  <span className="sm:hidden">Tout lire</span>
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="opacity-50 hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-gray-50"
                aria-label="Fermer"
              >
                <X size={14} style={{ color: '#5D6D7E' }} />
              </button>
            </div>
          </div>

          {/* Corps */}
          <div style={{ maxHeight: 400, overflowY: 'auto' }}>
            {loading ? (
              /* Squelette de chargement */
              <div className="p-4 space-y-3">
                {[1, 2, 3].map(i => (
                  <div key={i} className="flex gap-3">
                    <div className="w-7 h-7 rounded-md animate-pulse shrink-0" style={{ background: '#F0F4F9' }} />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-3 rounded animate-pulse w-3/4" style={{ background: '#F0F4F9' }} />
                      <div className="h-2.5 rounded animate-pulse w-full" style={{ background: '#F0F4F9' }} />
                      <div className="h-2.5 rounded animate-pulse w-1/2" style={{ background: '#F0F4F9' }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : visible.length === 0 ? (
              /* État vide */
              <div className="flex flex-col items-center py-12 gap-3">
                <div
                  className="w-12 h-12 rounded-full flex items-center justify-center"
                  style={{ background: '#F0F4F9' }}
                >
                  <Bell size={22} style={{ color: '#D5E8F5' }} />
                </div>
                <div className="text-center">
                  <p className="text-xs font-medium" style={{ color: '#5D6D7E' }}>Aucune notification</p>
                  <p className="text-[11px] mt-0.5" style={{ color: '#9BAFBF' }}>
                    Les alertes factures et budget apparaîtront ici.
                  </p>
                </div>
              </div>
            ) : (
              /* Liste */
              visible.map(item => {
                const meta = TYPE_META[item.type] ?? {
                  label: item.type,
                  color: '#5D6D7E',
                  bg: '#F0F4FA',
                  Icon: Bell,
                }
                const TypeIcon = meta.Icon
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
                      {/* Icône de type */}
                      <div
                        className="shrink-0 w-7 h-7 rounded-md flex items-center justify-center mt-0.5"
                        style={{ background: meta.bg }}
                      >
                        <TypeIcon size={13} style={{ color: meta.color }} />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <p
                            className="text-xs font-semibold"
                            style={{ color: '#1A1A2E', lineHeight: 1.4 }}
                          >
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

                        {/* Méta-infos */}
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5">
                          <span
                            className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                            style={{ background: meta.bg, color: meta.color }}
                          >
                            {meta.label}
                          </span>
                          <span className="text-[10px]" style={{ color: '#9BAFBF' }}>
                            {timeAgo(item.created_at)}
                          </span>
                          {!item.is_read && (
                            <span
                              className="w-1.5 h-1.5 rounded-full shrink-0"
                              style={{ background: '#C0391B' }}
                              title="Non lue"
                            />
                          )}
                          {item.invoice_id && (
                            <button
                              onClick={() => { navigate('/invoices'); setOpen(false) }}
                              className="flex items-center gap-0.5 text-[10px] font-medium hover:underline"
                              style={{ color: '#5BA3C9' }}
                            >
                              <FileText size={10} />
                              Voir facture
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* Pied : mention si items tronqués */}
          {items.length > MAX_VISIBLE && (
            <div
              className="px-4 py-2 text-center"
              style={{ borderTop: '1px solid #F0F4F9', background: '#FAFBFD' }}
            >
              <p className="text-[11px]" style={{ color: '#9BAFBF' }}>
                +{items.length - MAX_VISIBLE} notification
                {items.length - MAX_VISIBLE > 1 ? 's' : ''} supplémentaire
                {items.length - MAX_VISIBLE > 1 ? 's' : ''}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
