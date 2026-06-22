import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
  children: ReactNode
}

const variantStyles: Record<Variant, { bg: string; color: string; border: string; hover: string }> = {
  primary:   { bg: '#1A3A5C', color: '#fff',     border: 'transparent', hover: '#244E82' },
  secondary: { bg: '#fff',    color: '#1A3A5C',  border: '#D5E8F5',     hover: '#F0F4F9' },
  danger:    { bg: '#fff',    color: '#C0391B',  border: '#FDECEA',     hover: '#FEF2F2' },
  ghost:     { bg: 'transparent', color: '#5D6D7E', border: 'transparent', hover: '#F0F4F9' },
}

const sizeStyles: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  lg: 'px-5 py-2.5 text-sm gap-2',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  icon,
  children,
  disabled,
  className = '',
  style,
  ...rest
}: Props) {
  const v = variantStyles[variant]
  return (
    <button
      {...rest}
      disabled={disabled}
      className={`inline-flex items-center font-semibold rounded-lg border transition-all disabled:opacity-50 disabled:cursor-not-allowed ${sizeStyles[size]} ${className}`}
      style={{
        background: v.bg,
        color: v.color,
        borderColor: v.border,
        ...style,
      }}
      onMouseEnter={e => { if (!disabled) (e.currentTarget as HTMLButtonElement).style.background = v.hover }}
      onMouseLeave={e => { if (!disabled) (e.currentTarget as HTMLButtonElement).style.background = v.bg }}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      {children}
    </button>
  )
}
