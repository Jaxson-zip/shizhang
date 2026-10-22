import { useT, Button } from '@beecount/ui'
import { useAuth } from '../context/AuthContext'
import { useSyncConnection } from '../context/SyncSocketContext'

export type ConnectionState = { online: boolean; socket: string; pull: string; checkedAt: number | null }
export function connectionMessage(state: ConnectionState) {
  if (!state.online) return 'syncState.offline'
  if (state.pull === 'auth') return 'syncState.auth'
  if (state.pull === 'error') return 'syncState.error'
  if (state.pull === 'checking') return 'syncState.checking'
  if (state.socket === 'connected') return 'syncState.connected'
  return 'syncState.reconnecting'
}

/** Connection and pull status only; never claims every page or write is synchronized. */
export function SyncStatusView({ state, checkNow, login }: { state: ConnectionState; checkNow: () => void; login: () => void }) {
  const t = useT()
  const key = connectionMessage(state)
  const warning = !state.online || state.pull === 'error' || state.pull === 'auth'
  return <details className={`rounded-xl border px-3 text-sm ${warning ? 'border-amber-600/40 bg-amber-500/10 text-foreground' : 'border-border/50 bg-card/50 text-muted-foreground'}`}>
    <summary className="min-h-11 cursor-pointer py-3 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span role="status">{t(key)}</span>
    </summary>
    <div className="space-y-2 border-t border-border/50 py-3 text-sm leading-relaxed">
      <p>{t(!state.online ? 'syncState.offlineHelp' : state.pull === 'auth' ? 'syncState.authHelp' : 'syncState.help')}</p>
      {state.checkedAt !== null ? <p className="text-xs">{t('syncState.checkedAt')} {new Date(state.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p> : null}
      <Button type="button" variant="outline" disabled={!state.online} aria-disabled={state.pull === 'checking'} className="aria-disabled:opacity-50" onClick={() => {
        if (state.pull === 'checking') return
        if (state.pull === 'auth') login()
        else checkNow()
      }}>
        {t(state.pull === 'auth' ? 'syncState.login' : state.pull === 'checking' ? 'syncState.checking' : 'syncState.check')}
      </Button>
    </div>
  </details>
}

export function SyncStatusNotice() {
  const connection = useSyncConnection()
  const { logout } = useAuth()
  return <SyncStatusView state={connection} checkNow={connection.checkNow} login={logout} />
}
