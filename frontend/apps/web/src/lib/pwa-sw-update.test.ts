import { afterEach, describe, expect, it, vi } from 'vitest'

describe('PWA update consent', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.resetModules()
  })

  it('clears availability when another tab activates the waiting worker, without reloading this draft', async () => {
    vi.useFakeTimers()
    const workers = Object.assign(new EventTarget(), { controller: {} })
    const reload = vi.fn()
    const win = Object.assign(new EventTarget(), { location: { reload } })
    vi.stubGlobal('navigator', { serviceWorker: workers })
    vi.stubGlobal('window', win)
    const waiting = Object.assign(new EventTarget(), { state: 'installed', postMessage: vi.fn() })
    const registration = Object.assign(new EventTarget(), {
      waiting: waiting as typeof waiting | null, installing: null, update: vi.fn().mockResolvedValue(undefined),
    })
    const updates = await import('./pwa-sw-update')
    const availability: boolean[] = []
    win.addEventListener(updates.SW_UPDATE_EVENT, () => availability.push(updates.hasServiceWorkerUpdate()))
    updates.setupServiceWorkerUpdates(registration as unknown as ServiceWorkerRegistration)
    expect(availability[availability.length - 1]).toBe(true)
    registration.waiting = null
    workers.dispatchEvent(new Event('controllerchange'))
    expect(availability[availability.length - 1]).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })

  it('removes a discarded worker and ignores an accept click after it stopped waiting', async () => {
    vi.useFakeTimers()
    const workers = Object.assign(new EventTarget(), { controller: {} })
    const reload = vi.fn()
    const win = Object.assign(new EventTarget(), { location: { reload } })
    vi.stubGlobal('navigator', { serviceWorker: workers })
    vi.stubGlobal('window', win)
    const waiting = Object.assign(new EventTarget(), { state: 'installed', postMessage: vi.fn() })
    const registration = Object.assign(new EventTarget(), { waiting, installing: null, update: vi.fn().mockResolvedValue(undefined) })
    const updates = await import('./pwa-sw-update')
    const availability: boolean[] = []
    win.addEventListener(updates.SW_UPDATE_EVENT, () => availability.push(updates.hasServiceWorkerUpdate()))
    const stop = updates.setupServiceWorkerUpdates(registration as unknown as ServiceWorkerRegistration)
    waiting.state = 'redundant'
    waiting.dispatchEvent(new Event('statechange'))
    await Promise.resolve()
    expect(availability[availability.length - 1]).toBe(false)
    updates.acceptServiceWorkerUpdate()
    workers.dispatchEvent(new Event('controllerchange'))
    expect(waiting.postMessage).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
    stop()
    expect(vi.getTimerCount()).toBe(0)
    expect(updates.hasServiceWorkerUpdate()).toBe(false)
  })

  it('does not reload an open form when a worker first takes control', async () => {
    vi.useFakeTimers()
    const workers = Object.assign(new EventTarget(), { controller: {} })
    const reload = vi.fn()
    vi.stubGlobal('navigator', { serviceWorker: workers })
    vi.stubGlobal('window', Object.assign(new EventTarget(), { location: { reload } }))
    const registration = Object.assign(new EventTarget(), {
      waiting: null, installing: null, update: vi.fn().mockResolvedValue(undefined),
    })
    const { setupServiceWorkerUpdates } = await import('./pwa-sw-update')
    setupServiceWorkerUpdates(registration as unknown as ServiceWorkerRegistration)

    workers.dispatchEvent(new Event('controllerchange'))

    expect(reload).not.toHaveBeenCalled()
  })

  it('keeps a pending update discoverable after login and reloads once only after acceptance', async () => {
    vi.useFakeTimers()
    const workers = Object.assign(new EventTarget(), { controller: {} })
    const reload = vi.fn()
    const postMessage = vi.fn()
    vi.stubGlobal('navigator', { serviceWorker: workers })
    vi.stubGlobal('window', Object.assign(new EventTarget(), { location: { reload } }))
    const registration = Object.assign(new EventTarget(), {
      waiting: Object.assign(new EventTarget(), { state: 'installed', postMessage }), installing: null, update: vi.fn().mockResolvedValue(undefined),
    })
    const updates = await import('./pwa-sw-update')
    updates.setupServiceWorkerUpdates(registration as unknown as ServiceWorkerRegistration)

    expect(updates.hasServiceWorkerUpdate()).toBe(true)
    expect(reload).not.toHaveBeenCalled()
    updates.acceptServiceWorkerUpdate()
    expect(postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' })
    workers.dispatchEvent(new Event('controllerchange'))
    workers.dispatchEvent(new Event('controllerchange'))
    expect(reload).toHaveBeenCalledTimes(1)
  })
})
