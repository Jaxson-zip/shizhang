import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react'
import { usePageCache } from '../context/PageDataCacheContext'
import { createCalendarRead } from '../lib/calendar-state'

export function useCalendarRead<T>(key: string, read: () => Promise<T>, enabled: boolean) {
  const [cached, setCached] = usePageCache<{ key: string; data: T } | null>(key, null)
  // The existing page cache's local state does not reset on key changes. Only
  // hydrate a matching period; each period gets its own request generation.
  const reader = useMemo(() => createCalendarRead<T>(cached?.key === key ? cached.data : null), [key])
  const state = useSyncExternalStore(reader.subscribe, reader.getSnapshot, reader.getSnapshot)
  const reload = useCallback(() => {
    if (!enabled) return Promise.resolve()
    return reader.load(read, (data) => setCached({ key, data }))
  }, [reader, read, enabled, setCached, key])
  useEffect(() => {
    void reload()
    return reader.cancel
  }, [reader, reload])
  return { ...state, reload }
}
