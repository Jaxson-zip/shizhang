import type { ReactNode } from 'react'
import { DialogClose, DialogHeader, useT } from '@beecount/ui'
import { X } from 'lucide-react'

import type { DetailScope } from '../../lib/txDialogEvents'
import { DetailScopeToggle } from './DetailScopeToggle'

/** Keep the close control in normal layout, separate from the scope switcher. */
export function DetailDialogHeader({ children, scope, onScopeChange }: {
  children: ReactNode
  scope: DetailScope
  onScopeChange: (next: DetailScope) => void
}) {
  const t = useT()
  return (
    <DialogHeader className="shrink-0 space-y-0 border-b border-border/60 px-4 py-3 sm:px-6">
      <div data-detail-dialog-header className="grid grid-cols-[minmax(0,1fr)_44px] items-center gap-3 sm:grid-cols-[minmax(0,1fr)_auto_44px]">
        <div className="col-start-1 row-start-1 min-w-0">{children}</div>
        <DetailScopeToggle value={scope} onChange={onScopeChange} className="col-span-2 row-start-2 sm:col-span-1 sm:col-start-2 sm:row-start-1" />
        <DialogClose className="col-start-2 row-start-1 inline-flex h-11 w-11 items-center justify-center self-start rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:col-start-3" aria-label={t('common.close')}>
          <X className="h-5 w-5" />
        </DialogClose>
      </div>
    </DialogHeader>
  )
}
