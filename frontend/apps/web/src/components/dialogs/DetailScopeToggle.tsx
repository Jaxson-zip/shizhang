import { useT } from '@beecount/ui'

import type { DetailScope } from '../../lib/txDialogEvents'

interface Props {
  value: DetailScope
  onChange: (next: DetailScope) => void
  className?: string
}

/**
 * 详情弹窗顶部的"全部账本 / 当前账本"切换。复用 i18n 现有键 shell.allLedgers
 * + home.scope.current,不再引入新文案。被 AccountDetail / CategoryDetail /
 * TagDetail 三处弹窗共用,所以放在 components/dialogs/。
 */
export function DetailScopeToggle({ value, onChange, className }: Props) {
  const t = useT()
  const options: Array<{ key: DetailScope; label: string }> = [
    { key: 'all', label: t('shell.allLedgers') },
    { key: 'current', label: t('home.scope.current') },
  ]
  return (
    <div
      role="tablist"
      aria-label={t('shell.allLedgers')}
      className={`grid grid-cols-2 rounded-xl border border-border/60 bg-muted/30 p-1 text-sm ${className || ''}`}
    >
      {options.map((opt) => {
        const active = opt.key === value
        return (
          <button
            key={opt.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.key)}
            className={`min-h-11 whitespace-nowrap rounded-lg px-3 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
              active
                ? 'bg-background font-semibold text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
