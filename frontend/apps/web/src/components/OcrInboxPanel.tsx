import { Button } from '@beecount/ui'
import type { TxForm } from '@beecount/web-features'
import { captureEntryState, captureGaps, type OcrInboxItem, type OcrInboxView } from '../lib/ocr-inbox'
import { CapturePictureView } from './CapturePicture'

const ENTRY_LABEL = {
  unbooked: '已收下 · 尚未入账',
  provisional: '已记临时账目 · 暂不计收支统计',
  counted: '已入账并计入统计 · 待确认核对',
  missing: '关联账目已删除或不可见 · 请刷新后处理',
  linked: '已有关联账目 · 待核对',
} as const
export type OcrInboxSource = { id: string; loading: boolean; error?: string; imageUrl?: string; imageError?: string }
function captureTime(raw: string) {
  const date = new Date(raw)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '时间待确认'
}

export function OcrInboxPanel({ items, total, loading, error, busy, onRetry, onMore, onReview,
  view = 'pending', pendingTotal = total, ignoredTotal = 0, onViewChange, onChangeState, notice, source, onViewSource, onReread }: {
  items: OcrInboxItem[]; total: number; loading: boolean; error: string; busy?: string
  onRetry: () => void; onMore: () => void
  onReview: (item: OcrInboxItem, type: TxForm['tx_type']) => void
  view?: OcrInboxView; pendingTotal?: number; ignoredTotal?: number
  onViewChange?: (view: OcrInboxView) => void
  onChangeState?: (item: OcrInboxItem, state: OcrInboxView) => void
  notice?: { text: string; undo?: () => void } | null
  source?: OcrInboxSource | null; onViewSource?: (item: OcrInboxItem) => void
  onReread?: (item: OcrInboxItem) => void
}) {
  return <section aria-label="稍后核对" className="rounded-2xl border border-border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-base font-semibold">稍后核对{pendingTotal > 0 ? ` · ${pendingTotal}` : ''}</h2>
      <Button variant="ghost" size="sm" onClick={onRetry} disabled={loading || Boolean(busy)}>刷新</Button>
    </div>
    <div role="group" aria-label="采集状态" className="mt-3 flex flex-wrap gap-2">
      <Button variant={view === 'pending' ? 'secondary' : 'ghost'} className="min-h-11" aria-pressed={view === 'pending'} disabled={Boolean(busy)} onClick={() => onViewChange?.('pending')}>待核对{`（${pendingTotal}）`}</Button>
      <Button variant={view === 'ignored' ? 'secondary' : 'ghost'} className="min-h-11" aria-pressed={view === 'ignored'} disabled={Boolean(busy)} onClick={() => onViewChange?.('ignored')}>已忽略{`（${ignoredTotal}）`}</Button>
    </div>
    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{view === 'ignored'
      ? '这些采集尚未入账。原文仍保留，恢复后可继续补全；忽略和恢复都不增删账目。'
      : '付款时先收下，方便时再看。视觉补读等需核对的账目先记为临时账目，暂不计收支统计，确认后才计入；金额或方向不明的内容尚未入账。'}</p>
    {notice ? <div role="status" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-muted/50 p-3 text-sm"><span>{notice.text}</span>{notice.undo ? <Button variant="outline" className="min-h-11" disabled={Boolean(busy)} onClick={notice.undo}>撤销忽略</Button> : null}</div> : null}
    {loading ? <p role="status" className="mt-3 text-sm">正在读取待核对内容…</p> : null}
    {error ? <p role="alert" className="mt-3 text-sm text-destructive">{error} <button type="button" disabled={loading || Boolean(busy)} className="min-h-11 underline" onClick={onRetry}>重新读取</button></p> : null}
    {!loading && !error && !total ? <p className="mt-3 text-sm text-muted-foreground">{view === 'ignored' ? '暂无已忽略的采集。' : '暂无待核对内容。'}</p> : null}
    <ul className="mt-3 divide-y divide-border">
      {items.map(item => <li key={item.id} className="space-y-2 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="break-words text-sm font-medium">{item.draft?.note || '付款信息待补全'}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{view === 'ignored' ? '已忽略 · 尚未入账' : ENTRY_LABEL[captureEntryState(item)]}</p>
          </div>
          <p className="shrink-0 text-base font-semibold tabular-nums">{item.draft ? `${item.draft.type === 'income' ? '+' : '−'}¥${item.draft.amount.toFixed(2)}` : '金额待核对'}</p>
        </div>
        <p className="break-words text-sm leading-relaxed text-muted-foreground">{item.reason}</p>
        {view === 'pending' && !item.entity_id && captureGaps(item).length ? <p className="text-sm leading-relaxed">待补：{captureGaps(item).join('、')}</p> : null}
        <p className="text-xs leading-relaxed text-muted-foreground">采集时间（北京时间）：{captureTime(item.created_at)}</p>
        {item.image ? <p className="text-xs leading-relaxed text-muted-foreground">{item.image.available && item.image.expires_at
          ? `临时截图保留至 ${captureTime(item.image.expires_at)}（北京时间）；核对、忽略或超额时提前清理。`
          : '临时截图未上传或已清理；原文与账目不受影响。'}</p> : null}
        {source?.id === item.id ? <CapturePictureView loading={source.loading} imageUrl={source.imageUrl} error={source.error || source.imageError} /> : null}
        {view === 'pending' && !item.entity_id && item.image?.available && onReread ? <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-muted/30 p-3">
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-muted-foreground">用你配置的视觉服务补读截图，可能产生费用；仅更新草稿，不新增账目。</p>
          <Button variant="outline" className="min-h-11" disabled={loading || Boolean(busy)} onClick={() => onReread(item)}>{busy === item.id ? '正在处理…' : '用截图重新识别'}</Button>
        </div> : null}
        <div className="flex flex-wrap items-center justify-end gap-2">
          {onViewSource ? <Button variant="ghost" className="mr-auto min-h-11" disabled={Boolean(busy)} aria-expanded={source?.id === item.id} onClick={() => onViewSource(item)}>{source?.id === item.id ? '收起截图' : '查看截图'}</Button> : null}
          {view === 'ignored' ? <Button variant="outline" className="min-h-11" disabled={loading || Boolean(busy)} onClick={() => onChangeState?.(item, 'pending')}>恢复待核对</Button> : <>
            {(!item.entity_id || captureEntryState(item) === 'missing') && onChangeState ? <Button variant="ghost" className="min-h-11" disabled={loading || Boolean(busy)} onClick={() => onChangeState(item, 'ignored')}>忽略这次采集</Button> : null}
            {captureEntryState(item) === 'missing' ? null : item.entity_id || item.draft ? <Button variant="outline" className="min-h-11" disabled={loading || Boolean(busy)} onClick={() => onReview(item, item.draft?.type || 'expense')}>核对这笔</Button>
              : (['expense', 'income', 'transfer'] as const).map(type => <Button key={type} variant="outline" className="min-h-11" disabled={loading || Boolean(busy)} onClick={() => onReview(item, type)}>
                {type === 'expense' ? '补记支出' : type === 'income' ? '补记收入' : '补记转账'}</Button>)}
          </>}
        </div>
      </li>)}
    </ul>
    {total > items.length ? <Button variant="outline" className="mt-2 min-h-11 w-full" onClick={onMore} disabled={loading || Boolean(busy)}>查看更多（已显示 {items.length} / {total}）</Button> : null}
  </section>
}
