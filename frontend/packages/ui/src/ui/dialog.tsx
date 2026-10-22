import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'

import { cn } from '../lib/cn'
import { useT } from '../locale/LocaleProvider'

const Dialog = DialogPrimitive.Root

const DialogTrigger = DialogPrimitive.Trigger

const DialogPortal = DialogPrimitive.Portal

const DialogClose = DialogPrimitive.Close

function DialogOverlay({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      className={cn('fixed inset-0 z-50 bg-black/50 backdrop-blur-[1px]', className)}
      {...props}
    />
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  fitViewport = true,
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { showCloseButton?: boolean; fitViewport?: boolean }) {
  const t = useT()
  const returnFocus = React.useRef<HTMLElement | null>(null)
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        className={cn(
          'bc-dialog-content fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100dvh-2rem)] w-[92vw] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-xl border border-border bg-card p-6 text-card-foreground shadow-soft',
          className
        )}
        data-default-close={showCloseButton ? 'true' : undefined}
        data-viewport-fit={fitViewport ? 'true' : undefined}
        onOpenAutoFocus={(event) => {
          const active = document.activeElement
          returnFocus.current = active instanceof HTMLElement && active !== document.body ? active : null
          onOpenAutoFocus?.(event)
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event)
          if (event.defaultPrevented) return
          const target = returnFocus.current
          if (!target?.isConnected || target.matches(':disabled,[aria-disabled="true"]')) return
          const openDialogs = Array.from(document.querySelectorAll('[role="dialog"][data-state="open"]'))
          if (openDialogs.length && !openDialogs.some((dialog) => dialog.contains(target))) return
          event.preventDefault()
          target.focus({ preventScroll: true })
        }}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close className="absolute right-2 top-2 inline-flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={t('common.close')}>
            <X className="h-5 w-5" />
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('bc-dialog-header flex min-h-11 shrink-0 flex-col space-y-1.5 text-left', className)} {...props} />
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex shrink-0 flex-wrap items-center justify-end gap-2', className)} {...props} />
}

function DialogTitle({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn('text-base font-semibold', className)} {...props} />
}

function DialogDescription({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn('text-sm text-muted-foreground', className)} {...props} />
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger
}
