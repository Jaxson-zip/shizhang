import { useCallback, useEffect, useRef, useState } from 'react'
import { usePageCache } from '../context/PageDataCacheContext'

/** Read status only; callers retain their existing API/data and write paths. */
export function usePageReadStatus(cacheKey: string) {
  const [ready, setReady] = usePageCache(`${cacheKey}:read-confirmed`, false)
  const [pending, setPending] = useState(!ready)
  const [failed, setFailed] = useState(false)
  const sequence = useRef(0)
  useEffect(() => () => { sequence.current += 1 }, [])
  const begin = useCallback(() => { setPending(true); return ++sequence.current }, [])
  const isCurrent = useCallback((request: number) => sequence.current === request, [])
  const finish = useCallback((request: number, succeeded: boolean) => {
    if (sequence.current !== request) return
    if (succeeded) setReady(true)
    setFailed(!succeeded)
    setPending(false)
  }, [setReady])
  return { ready, pending, failed, begin, finish, isCurrent }
}
