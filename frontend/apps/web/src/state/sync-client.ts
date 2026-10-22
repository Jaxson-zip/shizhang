import { authedGet, ApiError } from '@beecount/api-client'

const POLL_INTERVAL_MS = 30_000

export interface SyncChangeEnvelope {
  change_id: number
  ledger_id: string
  entity_type: string
  entity_sync_id: string
  action: string
  payload: unknown
  updated_at: string
  updated_by_device_id?: string | null
}

export interface SyncPullResponse {
  changes: SyncChangeEnvelope[]
  server_cursor: number
  has_more: boolean
}

export type SyncPullResult = { changes: SyncChangeEnvelope[]; cursor: number; complete: boolean; errorStatus?: number }

function cursorKey(userId: string): string {
  return `beecount.sync.cursor.${userId}`
}

export function loadCursor(userId: string): number {
  if (typeof window === 'undefined') return 0
  const raw = window.localStorage.getItem(cursorKey(userId))
  const parsed = raw ? Number.parseInt(raw, 10) : 0
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

export function saveCursor(userId: string, cursor: number): void {
  if (typeof window === 'undefined') return
  if (!Number.isFinite(cursor) || cursor <= 0) return
  const current = loadCursor(userId)
  if (cursor <= current) return
  window.localStorage.setItem(cursorKey(userId), String(cursor))
}

export function clearCursor(userId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(cursorKey(userId))
}

/**
 * Fetch all changes since the caller's last-known cursor, draining the
 * ``has_more`` flag so callers don't have to loop manually. Returns the
 * final server cursor (already persisted) and total change count.
 */
export async function drainPull(
  token: string,
  userId: string,
  deviceId: string | null
): Promise<SyncPullResult> {
  let cursor = loadCursor(userId)
  const collected: SyncChangeEnvelope[] = []
  // Cap the drain loop so a misbehaving server can't spin us forever.
  for (let iteration = 0; iteration < 50; iteration += 1) {
    const params = new URLSearchParams()
    params.set('since', String(cursor))
    params.set('limit', '1000')
    if (deviceId) params.set('device_id', deviceId)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15_000)
    let body: SyncPullResponse
    try {
      body = await authedGet<SyncPullResponse>(`/sync/pull?${params.toString()}`, token, controller.signal)
    } catch (error) {
      // Earlier pages may already have advanced the cursor; still deliver those changes.
      return { changes: collected, cursor, complete: false, ...(error instanceof ApiError ? { errorStatus: error.status } : {}) }
    } finally { clearTimeout(timeout) }
    if (!Array.isArray(body.changes) || !Number.isSafeInteger(body.server_cursor) || body.server_cursor < cursor || typeof body.has_more !== 'boolean') {
      return { changes: collected, cursor, complete: false }
    }
    if (Array.isArray(body.changes) && body.changes.length > 0) {
      collected.push(...body.changes)
    }
    if (typeof body.server_cursor === 'number' && body.server_cursor > cursor) {
      cursor = body.server_cursor
      saveCursor(userId, cursor)
    }
    if (!body.has_more) return { changes: collected, cursor, complete: true }
  }
  return { changes: collected, cursor, complete: false }
}

export interface PollerControls {
  stop: () => void
  /** Force an immediate drain; honors in-flight ticks via a single-flight lock. */
  tickNow: () => Promise<void>
}

/**
 * Background polling fallback. Runs every POLL_INTERVAL_MS while the tab is
 * visible and a token is set. When WebSocket delivery is alive, this layer
 * just no-ops past the server's since-filter; when WS is down, it catches up.
 */
export function startPoller(params: {
  token: string
  userId: string
  deviceId: string | null
  onChanges: (changes: SyncChangeEnvelope[]) => void
  onStart?: () => void
  onResult?: (result: SyncPullResult) => void
  onError?: () => void
}): PollerControls {
  let stopped = false
  let inflight = false
  async function tick() {
    if (stopped || inflight) return
    if (typeof document !== 'undefined' && document.hidden) return
    inflight = true
    params.onStart?.()
    try {
      const result = await drainPull(params.token, params.userId, params.deviceId)
      const { changes } = result
      if (changes.length > 0 && !stopped) {
        params.onChanges(changes)
      }
      if (!stopped) params.onResult?.(result)
    } catch (_) {
      if (!stopped) params.onError?.()
    } finally {
      inflight = false
    }
  }

  const interval = setInterval(tick, POLL_INTERVAL_MS)
  // Run once on start so a freshly-mounted page picks up anything missed.
  void tick()

  return {
    stop: () => {
      stopped = true
      clearInterval(interval)
    },
    tickNow: () => tick()
  }
}
