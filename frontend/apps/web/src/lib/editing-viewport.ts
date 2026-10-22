import { observeDialogViewport } from './dialog-viewport'

const editableSelector = 'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]):not([type="button"]):not([type="submit"]):not(:disabled):not([readonly]),textarea:not(:disabled):not([readonly]),[contenteditable="true"],[contenteditable=""]'
const clips = /^(auto|scroll|hidden|clip)$/
const padding = 12

/** Shared app input visibility. Scroll only as far as needed, never change focus/zoom/value. */
export function observeEditingViewport(target: Window, doc: Document) {
  const root = doc.documentElement
  let frame = 0
  let stopped = false
  let gesture = false
  let dragged = false
  let gestureStart: { x: number; y: number } | null = null
  let focusPending = false
  let resizeObserver: ResizeObserver | null = null

  const cancel = () => { if (frame) target.cancelAnimationFrame(frame); frame = 0 }
  const activeInput = () => {
    const active = doc.activeElement as HTMLElement | null
    return active?.isConnected && active.matches(editableSelector) && !active.closest('[aria-hidden="true"],[inert]') ? active : null
  }
  const reduced = () => (target.visualViewport?.scale ?? 1) <= 1.05
    && (target.visualViewport?.height ?? target.innerHeight) < target.innerHeight - 80

  const reveal = () => {
    const active = activeInput()
    if (!active || gesture || (target.visualViewport?.scale ?? 1) > 1.05) return
    if (target.innerWidth >= 768 && !reduced() && !target.matchMedia('(pointer: coarse)').matches) return
    focusPending = false
    const viewport = target.visualViewport
    const viewportTop = (viewport?.offsetTop ?? 0) + padding
    const viewportBottom = (viewport?.offsetTop ?? 0) + (viewport?.height ?? target.innerHeight) - padding
    const parents: HTMLElement[] = []
    for (let p = active.parentElement; p && p !== doc.body && p !== root; p = p.parentElement) parents.push(p)

    function move(container: HTMLElement, page = false) {
      let top = viewportTop, bottom = viewportBottom
      // Descendant clips move along with this scroller; intersect only this container and its ancestors.
      const start = page ? parents.length : Math.max(0, parents.indexOf(container))
      for (const p of parents.slice(start)) {
        if (!clips.test(target.getComputedStyle(p).overflowY)) continue
        const rect = p.getBoundingClientRect()
        top = Math.max(top, rect.top + p.clientTop + padding)
        bottom = Math.min(bottom, rect.top + p.clientTop + p.clientHeight - padding)
      }
      if (page) {
        for (const [selector, edge] of [['.bc-app-header', 'top'], ['.bc-mobile-nav', 'bottom']] as const) {
          const bar = doc.querySelector(selector)
          if (!bar) continue
          const r = bar.getBoundingClientRect()
          if (r.height <= 0) continue
          if (edge === 'top' && r.top <= viewportTop && r.bottom > top) top = Math.min(bottom, r.bottom + padding)
          if (edge === 'bottom' && r.bottom >= viewportBottom && r.top < bottom) bottom = Math.max(top, r.top - padding)
        }
      }
      if (bottom <= top) return
      const rect = active!.getBoundingClientRect()
      // Oversized editors retain their internal caret scrolling; don't oscillate between their edges.
      const delta = rect.height > bottom - top
        ? rect.bottom < top ? rect.bottom - bottom : rect.top > bottom ? rect.top - top : 0
        : rect.top < top ? rect.top - top : rect.bottom > bottom ? rect.bottom - bottom : 0
      if (Math.abs(delta) <= 1) return
      container.scrollTop = Math.max(0, Math.min(container.scrollHeight - container.clientHeight, container.scrollTop + delta))
    }
    // A second bounded pass handles an inner scroller made visible by an outer one.
    for (let pass = 0; pass < 2; pass++) {
      for (const p of parents) {
        if (/^(auto|scroll)$/.test(target.getComputedStyle(p).overflowY) && p.scrollHeight > p.clientHeight + 1) move(p)
      }
      // A fixed modal owns its scroll. Never pan the locked page underneath it.
      if (!active.closest('[role="dialog"],[role="alertdialog"]') && doc.scrollingElement) move(doc.scrollingElement as HTMLElement, true)
    }
  }
  const schedule = () => {
    if (stopped) return
    // A keyboard resize during a tap must be retried on release, even if this
    // field already had focus and therefore emits no second focusin event.
    if (gesture) { if (!dragged) focusPending = true; return }
    cancel()
    // Viewport resize can precede React/CSS layout. Measure after layout has settled.
    frame = target.requestAnimationFrame(() => {
      frame = target.requestAnimationFrame(() => { frame = 0; if (!stopped) reveal() })
    })
  }
  const onFocus = () => {
    focusPending = true
    resizeObserver?.disconnect()
    const active = activeInput()
    if (active && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(schedule)
      resizeObserver.observe(active)
      const dialog = active.closest('[role="dialog"],[role="alertdialog"]')
      if (dialog) resizeObserver.observe(dialog)
    }
    schedule()
  }
  const point = (event: Event) => {
    const p = (event as TouchEvent).touches?.[0] ?? event as PointerEvent
    return Number.isFinite(p.clientX) && Number.isFinite(p.clientY) ? { x: p.clientX, y: p.clientY } : null
  }
  const startGesture = (event: Event) => {
    if (!gesture) { dragged = false; gestureStart = point(event); focusPending = false }
    gesture = true; cancel()
  }
  const moveGesture = (event: Event) => {
    const p = point(event)
    if (gesture && gestureStart && p && Math.hypot(p.x - gestureStart.x, p.y - gestureStart.y) > 8) {
      dragged = true; focusPending = false
    }
  }
  const endGesture = (event: Event) => {
    if (event.type === 'pointercancel' || event.type === 'touchcancel') { dragged = true; focusPending = false }
    gesture = false
    if (focusPending && !dragged) schedule()
  }
  const stopViewport = observeDialogViewport(target, ({ height, top }) => {
    root.style.setProperty('--app-view-height', `${height}px`)
    root.style.setProperty('--app-view-top', `${top}px`)
    if (reduced()) root.setAttribute('data-editing-viewport', 'reduced')
    else root.removeAttribute('data-editing-viewport')
    if (reduced() && height < 240) root.setAttribute('data-editing-height', 'compact')
    else root.removeAttribute('data-editing-height')
    schedule()
  })
  doc.addEventListener('focusin', onFocus)
  doc.addEventListener('input', schedule)
  for (const event of ['pointerdown', 'touchstart']) doc.addEventListener(event, startGesture, { passive: true })
  for (const event of ['pointermove', 'touchmove']) doc.addEventListener(event, moveGesture, { passive: true })
  for (const event of ['pointerup', 'pointercancel', 'touchend', 'touchcancel']) doc.addEventListener(event, endGesture, { passive: true })
  return () => {
    stopped = true
    cancel()
    resizeObserver?.disconnect()
    stopViewport()
    doc.removeEventListener('focusin', onFocus)
    doc.removeEventListener('input', schedule)
    for (const event of ['pointerdown', 'touchstart']) doc.removeEventListener(event, startGesture)
    for (const event of ['pointermove', 'touchmove']) doc.removeEventListener(event, moveGesture)
    for (const event of ['pointerup', 'pointercancel', 'touchend', 'touchcancel']) doc.removeEventListener(event, endGesture)
    root.style.removeProperty('--app-view-height')
    root.style.removeProperty('--app-view-top')
    root.removeAttribute('data-editing-viewport')
    root.removeAttribute('data-editing-height')
  }
}
