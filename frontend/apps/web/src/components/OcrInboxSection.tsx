import { useCallback, useEffect, useRef, useState } from 'react'
import { authedGet, fetchWorkspaceTransactions } from '@beecount/api-client'
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle } from '@beecount/ui'
import type { TxForm } from '@beecount/web-features'
import { useAuth } from '../context/AuthContext'
import { useLedgers } from '../context/LedgersContext'
import { captureEntryState, changeOcrCaptureState, fetchCaptureImage, fetchOcrInbox, OCR_INBOX_CHANGED, ocrInboxForm, reparseCapture, rereadCaptureImage, type OcrCaptureState, type OcrInboxItem, type OcrInboxView } from '../lib/ocr-inbox'
import { readWithin } from '../lib/manual-preflight'
import { dispatchOpenEditTx, dispatchOpenNewTx } from '../lib/txDialogEvents'
import { OcrInboxPanel, type OcrInboxSource } from './OcrInboxPanel'

export function OcrInboxSection() {
  const [open, setOpen] = useState(false)
  const { token } = useAuth()
  const { activeLedgerId } = useLedgers()
  const [items, setItems] = useState<OcrInboxItem[]>([])
  const [total, setTotal] = useState(0)
  const [pendingTotal, setPendingTotal] = useState(0)
  const [ignoredTotal, setIgnoredTotal] = useState(0)
  const [recentTotal, setRecentTotal] = useState(0)
  const [view, setView] = useState<OcrInboxView>('pending')
  const [notice, setNotice] = useState<{ text: string; item?: OcrInboxItem } | null>(null)
  const [source, setSource] = useState<OcrInboxSource | null>(null)
  const sourceSequence = useRef(0)
  const previewUrl = useRef('')
  const releasePreview = () => { if (previewUrl.current) { URL.revokeObjectURL(previewUrl.current); previewUrl.current = '' } }
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const sequence = useRef(0)
  const operations = useRef(0)
  const busyRef = useRef('')
  const offset = useRef(0)
  const load = useCallback(async (more = false) => {
    if (!activeLedgerId) return
    const request = ++sequence.current
    setLoading(true); setError('')
    try {
      const page = await readWithin(() => fetchOcrInbox(token, activeLedgerId, more ? offset.current : 0, view))
      if (request !== sequence.current) return
      setItems(previous => more ? [...previous, ...page.items.filter(item => !previous.some(row => row.id === item.id))] : page.items)
      offset.current = (more ? offset.current : 0) + page.items.length
      setTotal(page.total)
      setPendingTotal(page.pending_total); setIgnoredTotal(page.ignored_total); setRecentTotal(page.recent_total ?? 0)
    } catch { if (request === sequence.current) setError('待核对内容读取失败，不能确认是否还有未处理记录。') }
    finally { if (request === sequence.current) setLoading(false) }
  }, [token, activeLedgerId, view])
  useEffect(() => { setNotice(null); setView('pending'); setOpen(false) }, [token, activeLedgerId])
  useEffect(() => {
    setItems([]); setTotal(0); setPendingTotal(0); setIgnoredTotal(0); setRecentTotal(0); offset.current = 0
    busyRef.current = ''; setBusy('')
    releasePreview(); setSource(null); sourceSequence.current++
    void load()
    const refresh = () => { if (document.visibilityState === 'visible') void load() }
    window.addEventListener(OCR_INBOX_CHANGED, refresh)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => { releasePreview(); sequence.current++; operations.current++; sourceSequence.current++; window.removeEventListener(OCR_INBOX_CHANGED, refresh)
      window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh) }
  }, [load])
  const viewSource = async (item: OcrInboxItem) => {
    const request = ++sourceSequence.current
    releasePreview()
    if (source?.id === item.id) { setSource(null); return }
    setSource({ id: item.id, loading: true })
    try {
      const detail = await readWithin(() => authedGet<OcrInboxItem>(`/ai/ocr-inbox/${encodeURIComponent(item.id)}`, token))
      if (request !== sourceSequence.current) return
      if (detail.ledger_id !== activeLedgerId || detail.id !== item.id) throw new Error('SOURCE_INVALID')
      setSource({ id: item.id, loading: Boolean(detail.image?.available) })
      if (detail.image?.available) {
        try {
          const image = await fetchCaptureImage(token, item.id)
          if (request !== sourceSequence.current) return
          previewUrl.current = URL.createObjectURL(image)
          setSource({ id: item.id, loading: false, imageUrl: previewUrl.current })
        } catch { if (request === sourceSequence.current) setSource({ id: item.id, loading: false, imageError: '截图已清理或暂时无法读取，可继续手动核对账目。' }) }
      }
    } catch { if (request === sourceSequence.current) setSource({ id: item.id, loading: false, error: '截图信息读取失败，请收起后重新打开。' }) }
  }
  const changeState = async (item: OcrInboxItem, target: OcrCaptureState) => {
    if (busyRef.current || item.ledger_id !== activeLedgerId) return
    const operation = ++operations.current
    busyRef.current = item.id; setBusy(item.id); setError(''); setNotice(null)
    releasePreview(); sourceSequence.current++; setSource(null)
    try {
      const result = await changeOcrCaptureState(token, item, target)
      if (operation !== operations.current) return
      setNotice(target === 'ignored' ? { text: '已忽略这次采集，账目未增删。', item: { ...item, ...result } }
        : { text: '已恢复到待核对，尚未入账。' })
      await load()
    } catch {
      if (operation !== operations.current) return
      await load()
      if (operation === operations.current) setError('操作结果尚未确认或状态已变化，请查看待核对及已忽略列表后再操作；账目不会因此新建或删除。')
    } finally { if (operation === operations.current) { busyRef.current = ''; setBusy('') } }
  }
  // Both re-reads only update the draft; neither creates an entry.
  const redraft = async (item: OcrInboxItem, run: typeof reparseCapture, failure: string) => {
    if (busyRef.current || item.ledger_id !== activeLedgerId) return
    const operation = ++operations.current
    busyRef.current = item.id; setBusy(item.id); setError(''); setNotice(null)
    releasePreview(); sourceSequence.current++; setSource(null)
    try {
      const result = await run(token, item)
      if (operation !== operations.current) return
      setNotice({ text: result.message })
      await load()
    } catch {
      if (operation !== operations.current) return
      await load()
      if (operation === operations.current) setError(failure)
    } finally { if (operation === operations.current) { busyRef.current = ''; setBusy('') } }
  }
  const reread = (item: OcrInboxItem) => redraft(item, rereadCaptureImage,
    '截图已清理、采集已变化或识别结果未确认，请刷新查看。此操作不会新增账目，请勿连续重试。')
  const reparse = (item: OcrInboxItem) => redraft(item, reparseCapture,
    '采集已变化或识别结果未确认，请刷新查看。此操作不会新增账目。')
  const review = async (item: OcrInboxItem, type: TxForm['tx_type']) => {
    if (busyRef.current) return
    const operation = ++operations.current
    const request = sequence.current
    busyRef.current = item.id; setBusy(item.id); setError('')
    try {
      const detail = await readWithin(() => authedGet<OcrInboxItem>(`/ai/ocr-inbox/${encodeURIComponent(item.id)}`, token))
      if (request !== sequence.current) return
      if (detail.status !== 'pending') { await load(); return }
      const state = captureEntryState(detail)
      const context = { id: item.id, requestKey: item.request_key,
        entry: state === 'unbooked' ? 'none' as const : state === 'provisional' || state === 'counted' ? state : undefined,
        form: ocrInboxForm(detail, type), allowedTypes: detail.draft ? [detail.draft.type, 'transfer'] as TxForm['tx_type'][] : undefined }
      if (detail.entity_id) {
        const page = await readWithin(() => fetchWorkspaceTransactions(token, { ledgerId: activeLedgerId!, txSyncId: detail.entity_id!, limit: 1 }))
        if (request !== sequence.current) return
        const tx = page.items.find(row => row.id === detail.entity_id)
        if (!tx) throw new Error('已记录的账目不在当前列表中，请刷新核对，不要另记一笔。')
        setOpen(false)
        dispatchOpenEditTx({ ...tx, ledger_id: item.ledger_id, ocrCapture: context })
      } else { setOpen(false); dispatchOpenNewTx({ ledgerId: item.ledger_id, ocrCapture: context }) }
    } catch { if (operation === operations.current) setError('无法打开这次核对，请刷新后重试；不会另记一笔。') }
    finally { if (operation === operations.current) { busyRef.current = ''; setBusy('') } }
  }
  return <>
    <Button type="button" variant="ghost" className="min-h-11 gap-2" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
      {error ? '核对读取失败' : '待核对'}{pendingTotal > 0 ? <span className="rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums">{pendingTotal}</span> : null}
    </Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="bc-manual-dialog flex max-h-[85dvh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border/60 px-5 py-4"><DialogTitle>采集核对</DialogTitle></DialogHeader>
        <div className="bc-manual-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4">
    <OcrInboxPanel items={items} total={total} loading={loading} error={error} busy={busy}
    view={view} pendingTotal={pendingTotal} ignoredTotal={ignoredTotal} onViewChange={setView}
    onChangeState={(item, target) => void changeState(item, target)}
    onReread={item => void reread(item)} onReparse={item => void reparse(item)} recentTotal={recentTotal}
    source={source} onViewSource={item => void viewSource(item)}
    notice={notice ? { text: notice.text, undo: notice.item ? () => void changeState(notice.item!, 'pending') : undefined } : null}
    onRetry={() => void load()} onMore={() => void load(true)} onReview={(item, type) => void review(item, type)} />
        </div>
      </DialogContent>
    </Dialog>
  </>
}
