interface Props {
  title: string
  badge?: string
  badgeVariant?: string
  children?: React.ReactNode
}

export default function PageHeader({ title, badge, children }: Props) {
  return (
    <div
      className="flex items-center gap-3 px-7 py-4 border-b sticky top-0 z-10"
      style={{ background: '#fff', borderColor: '#D5E8F5' }}
    >
      <h1 className="flex-1 text-lg font-bold m-0" style={{ color: '#1A1A2E' }}>{title}</h1>
      {badge && (
        <span className="px-3 py-1 rounded-full text-xs font-semibold bg-[#E3F0F9] text-[#5BA3C9]">
          {badge}
        </span>
      )}
      {children}
    </div>
  )
}
