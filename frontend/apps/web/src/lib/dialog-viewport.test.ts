import { describe, expect, it, vi } from 'vitest'

import { observeDialogViewport } from './dialog-viewport'

function browser() {
  const viewport = Object.assign(new EventTarget(), { height: 844, offsetTop: 0 })
  const target = Object.assign(new EventTarget(), { innerHeight: 844, visualViewport: viewport })
  return { target, viewport }
}

describe('dialog viewport', () => {
  it('tracks the area left above the keyboard and its scroll offset', () => {
    const { target, viewport } = browser()
    const report = vi.fn()
    const stop = observeDialogViewport(target, report)
    expect(report).toHaveBeenLastCalledWith({ height: 844, top: 0 })
    viewport.height = 390
    viewport.offsetTop = 52
    viewport.dispatchEvent(new Event('resize'))
    expect(report).toHaveBeenLastCalledWith({ height: 390, top: 52 })
    viewport.offsetTop = 64
    viewport.dispatchEvent(new Event('scroll'))
    expect(report).toHaveBeenLastCalledWith({ height: 390, top: 64 })
    stop()
    report.mockClear()
    viewport.dispatchEvent(new Event('resize'))
    viewport.dispatchEvent(new Event('scroll'))
    target.dispatchEvent(new Event('resize'))
    expect(report).not.toHaveBeenCalled()
  })

  it('falls back to the window height without a visual viewport', () => {
    const target = Object.assign(new EventTarget(), { innerHeight: 600, visualViewport: null })
    const report = vi.fn()
    const stop = observeDialogViewport(target, report)
    expect(report).toHaveBeenLastCalledWith({ height: 600, top: 0 })
    target.innerHeight = 420
    target.dispatchEvent(new Event('resize'))
    expect(report).toHaveBeenLastCalledWith({ height: 420, top: 0 })
    stop()
  })
})
