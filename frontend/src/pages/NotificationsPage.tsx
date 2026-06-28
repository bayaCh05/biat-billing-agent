import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, CheckCheck, AlertTriangle, Clock, FileText, TrendingUp, ExternalLink } from 'lucide-react'
import TopBar from '../components/layout/TopBar'
import { getNotificationList, markNotificationRead, markAllNotificationsRead } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import type { NotificationItem } from '../types'

const TYPE_META: Record<string, { label: string; color: string; bg: string; Icon: typeof Bell }> = {
  INVOICE_FLAGGED:   { label: 'Facture signalée',   color: '#C0391B', bg: '#FEF0EE', Icon: AlertTriangle },
  INVOICE_ESCALATED: { label: 'Facture escaladée',  color: '#804CD7', bg: '#F3EDFF', Icon: AlertTriangle },
  PAYMENT_OVERDUE:   { label: 'Paiement en retard', color: '#F0A600', bg: '#FEF9E7', Icon: Clock },
  BUDGET_EXCEEDED:   { label: 'Budget dépassé',     color: '#E67E22', bg: '#FEF5EC', Icon: TrendingUp },
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'À l\'instant'
  if (m < 60) return `Il y a ${m} min`
  const h = Math.floor(m / 60)
  if (h < 24) return `Il y a ${h}h`
  const d = Math.floor(h / 24)
  if (d < 7) return `Il y a ${d}j`
  return new Date(iso).toLocaleDateString('fr-TN', { day: '2-digit', month: 'short' })
}

function groupByDate(items: NotificationItem[]): [string, NotificationItem[]][] {
  const groups: Record<string, NotificationItem[]> = {}
  for (const n of items) {
    const d = new Date(n.created_at)
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(today.getDate() - 1)
    let key: string
    if (d.toDateString() === today.toDateString()) key = 'Aujourd\'hui'
    else if (d.toDateString() === yesterday.toDateString()) key = 'Hier'
    else key = d.toLocaleDateString('fr-TN', { weekday: 'long', day: '2-digit', month: 'long' })
    ;(groups[key] ??= []).push(n)
  }
  return Object.entries(groups)
}

export default function NotificationsPage() {
  const { setNotifCount } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [marking, setMarking] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    getNotificationList()
      .then(data => {
        setItems(data)
        setNotifCount?.(data.filter(n => !n.is_read).length)
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [setNotifCount])

  useEffect(() => { load() }, [load])

  const handleMarkRead = async (id: string) => {
    await markNotificationRead(id)
    setItems(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
    setNotifCount?.(prev => Math.max(0, (prev ?? 0) - 1))
  }

  const handleMarkAll = async () => {
    setMarking(true)
    await markAllNotificationsRead()
    setItems(prev => prev.map(n => ({ ...n, is_read: true })))
    setNotifCount?.(0)
    setMarking(false)
  }

  const unread = items.filter(n => !n.is_read).length
  const groups = groupByDate(items)

  return (
    <div className="flex flex-col h-full" style={{ background: '#F0F4FA', minHeight: 0 }}>
      <TopBar
        title="Notifications"
        badge={unread > 0 ? `${unread} non lue${unread > 1 ? 's' : ''}` : undefined}
      />

      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-2xl mx-auto">

          {/* Header actions */}
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-3">
              <Bell size={20} style={{ color: '#1A3A5C' }} />
              <span className="text-sm font-semibold" style={{ color: '#1A3A5C' }}>
                {items.length} notification{items.length !== 1 ? 's' : ''}
              </span>
              {unread > 0 && (
                <span
                  className="text-xs font-bold px-2 py-0.5 rounded-full text-white"
                  style={{ background: '#C0391B' }}
                >
                  {unread} non lue{unread > 1 ? 's' : ''}
                </span>
              )}
            </div>
            {unread > 0 && (
              <button
                onClick={handleMarkAll}
                disabled={marking}
                className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-all hover:shadow-sm disabled:opacity-50"
                style={{ color: '#1A3A5C', borderColor: '#D5E8F5', background: '#fff' }}
              >
                <CheckCheck size={13} />
                Tout marquer comme lu
              </button>
            )}
          </div>

          {/* Content */}
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: '#E2EAF3' }} />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center py-20 rounded-xl"
              style={{ background: '#fff', border: '1px solid #E2EAF3' }}
            >
              <Bell size={40} style={{ color: '#D5E8F5' }} />
              <p className="mt-4 text-sm font-medium" style={{ color: '#5D6D7E' }}>
                Aucune notification pour le moment.
              </p>
              <p className="text-xs mt-1" style={{ color: '#9BAFBF' }}>
                Les alertes factures et budget apparaîtront ici.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {groups.map(([day, notifs]) => (
                <section key={day}>
                  {/* Day separator */}
                  <div className="flex items-center gap-3 mb-3">
                    <span className="text-xs font-bold uppercase tracking-wider" style={{ color: '#9BAFBF' }}>
                      {day}
                    </span>
                    <div className="flex-1 h-px" style={{ background: '#E2EAF3' }} />
                  </div>

                  <div className="space-y-2">
                    {notifs.map(n => {
                      const meta = TYPE_META[n.type] ?? {
                        label: n.type,
                        color: '#5D6D7E',
                        bg: '#F0F4FA',
                        Icon: Bell,
                      }
                      const TypeIcon = meta.Icon

                      return (
                        <div
                          key={n.id}
                          className="flex gap-3 p-4 rounded-xl border transition-all"
                          style={{
                            background: n.is_read ? '#fff' : '#F5F9FF',
                            borderColor: n.is_read ? '#E2EAF3' : '#C3D9F0',
                          }}
                        >
                          {/* Type icon */}
                          <div
                            className="shrink-0 w-9 h-9 rounded-lg flex items-center justify-center mt-0.5"
                            style={{ background: meta.bg }}
                          >
                            <TypeIcon size={16} style={{ color: meta.color }} />
                          </div>

                          {/* Content */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>
                                  {n.title}
                                  {!n.is_read && (
                                    <span
                                      className="ml-2 inline-block w-2 h-2 rounded-full align-middle"
                                      style={{ background: '#C0391B' }}
                                    />
                                  )}
                                </p>
                                <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                                  {n.body}
                                </p>
                              </div>

                              {/* Actions */}
                              <div className="flex items-center gap-2 shrink-0">
                                {n.invoice_id && (
                                  <button
                                    onClick={() => navigate('/invoices')}
                                    className="flex items-center gap-1 text-xs font-medium hover:underline"
                                    style={{ color: '#5BA3C9' }}
                                    title="Voir la facture"
                                  >
                                    <FileText size={12} />
                                    Facture
                                    <ExternalLink size={10} />
                                  </button>
                                )}
                                {!n.is_read && (
                                  <button
                                    onClick={() => handleMarkRead(n.id)}
                                    className="text-xs font-medium hover:underline"
                                    style={{ color: '#1A3A5C' }}
                                  >
                                    Marquer lu
                                  </button>
                                )}
                              </div>
                            </div>

                            {/* Footer */}
                            <div className="flex items-center gap-3 mt-2">
                              <span
                                className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                                style={{ background: meta.bg, color: meta.color }}
                              >
                                {meta.label}
                              </span>
                              <span className="text-[11px]" style={{ color: '#9BAFBF' }}>
                                {timeAgo(n.created_at)}
                              </span>
                              {n.is_read && (
                                <span className="text-[11px]" style={{ color: '#9BAFBF' }}>
                                  ✓ Lu
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
