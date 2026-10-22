type EventSource = Pick<EventTarget, 'addEventListener' | 'removeEventListener'>
type ViewportWindow = EventSource & {
  innerHeight: number
  visualViewport: (EventSource & { height: number; offsetTop: number }) | null
}

export type DialogViewport = { height: number; top: number }

/** The visual viewport excludes the software keyboard; do not change zoom. */
export function observeDialogViewport(target: ViewportWindow, report: (value: DialogViewport) => void) {
  const viewport = target.visualViewport
  const update = () => report({ height: viewport?.height ?? target.innerHeight, top: viewport?.offsetTop ?? 0 })
  update()
  target.addEventListener('resize', update)
  viewport?.addEventListener('resize', update)
  viewport?.addEventListener('scroll', update)
  return () => {
    target.removeEventListener('resize', update)
    viewport?.removeEventListener('resize', update)
    viewport?.removeEventListener('scroll', update)
  }
}
