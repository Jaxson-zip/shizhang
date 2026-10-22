// Calendar display helpers; this module never changes stored amounts.
export function compactCalendarNet(value: number, chinese: boolean): string {
  const rounded = Math.round((Math.abs(value) + Number.EPSILON) * 100) / 100
  if (rounded === 0) return '0'
  const sign = value < 0 ? '-' : '+'
  if (rounded < 1) return sign + rounded.toFixed(2)
  let amount: string
  if (chinese) {
    amount = rounded < 1000 ? rounded.toFixed(0)
      : rounded < 10000 ? `${(rounded / 1000).toFixed(1)}k` : `${(rounded / 10000).toFixed(1)}万`
  } else {
    amount = rounded < 1000 ? rounded.toFixed(0)
      : rounded < 1_000_000 ? `${(rounded / 1000).toFixed(1)}k` : `${(rounded / 1_000_000).toFixed(1)}M`
  }
  return `≈${sign}${amount}`
}

export function exactCalendarNet(value: number, currency: string): string {
  const amount = (Math.round((Math.abs(value) + Number.EPSILON) * 100) / 100).toFixed(2)
  const sign = amount === '0.00' ? '' : value < 0 ? '-' : '+'
  return `${sign}${currency} ${amount}`
}

export function calendarCellExact(value: number): string {
  return exactCalendarNet(value, '').replace(' ', '')
}

export type CalendarReadState<T> = {
  data: T | null
  status: 'loading' | 'ready' | 'error'
  error: unknown
}

/** Local read lifecycle for a single calendar period; never retries writes. */
export function createCalendarRead<T>(initial: T | null = null) {
  let state: CalendarReadState<T> = { data: initial, status: initial === null ? 'loading' : 'ready', error: null }
  let generation = 0
  const listeners = new Set<() => void>()
  const publish = (next: CalendarReadState<T>) => {
    state = next
    listeners.forEach((notify) => notify())
  }
  return {
    getSnapshot: () => state,
    subscribe: (notify: () => void) => { listeners.add(notify); return () => { listeners.delete(notify) } },
    cancel: () => { generation++ },
    async load(read: () => Promise<T>, onSuccess?: (data: T) => void) {
      const current = ++generation
      publish({ ...state, status: 'loading', error: null })
      try {
        const data = await read()
        if (current !== generation) return
        publish({ data, status: 'ready', error: null })
        onSuccess?.(data)
      } catch (error) {
        if (current !== generation) return
        publish({ ...state, status: 'error', error })
      }
    },
  }
}
