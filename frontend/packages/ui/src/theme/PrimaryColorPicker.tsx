import { Check } from 'lucide-react'

import { useT } from '../locale/LocaleProvider'
import { PRIMARY_COLOR_PRESETS } from './primary-color-script'
import { usePrimaryColor } from './PrimaryColorProvider'

interface Props {
  /** 色板下方是否展示 `<input type="color">` 自定义色。默认 true。 */
  allowCustom?: boolean
  className?: string
}

/**
 * 预设色板 + 可选自定义色。
 *
 * 单向同步语义：mobile 改色 → server → web 无条件应用；web 本地改色只是
 * 临时切换，下一次 mobile 推送 / loadProfile 会覆盖；web 不会反向推给 mobile。
 */
export function PrimaryColorPicker({ allowCustom = true, className }: Props) {
  const { color, setColor } = usePrimaryColor()
  const t = useT()
  return (
    <div className={className}>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
        {PRIMARY_COLOR_PRESETS.map((preset) => {
          const selected = preset.toLowerCase() === color.toLowerCase()
          return (
            <button
              key={preset}
              type="button"
              aria-label={t('theme.primaryAria').replace('{color}', preset)}
              onClick={() => setColor(preset)}
              className={`flex h-11 w-11 items-center justify-center rounded-full border shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                selected ? 'border-foreground/40 ring-2 ring-foreground/50' : 'border-border/60'
              }`}
              style={{ background: preset }}
            >
              {selected ? <Check className="h-4 w-4" style={{ color: 'hsl(var(--primary-foreground))' }} /> : null}
            </button>
          )
        })}
      </div>
      {allowCustom ? (
        <label className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="uppercase tracking-wider">{t('theme.custom')}</span>
          <input
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="h-11 w-12 cursor-pointer rounded border border-border/60 bg-transparent"
          />
          <span className="font-mono text-[11px]">{color.toUpperCase()}</span>
        </label>
      ) : null}
    </div>
  )
}
