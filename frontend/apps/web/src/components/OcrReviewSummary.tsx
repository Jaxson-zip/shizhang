import type { TxForm } from '@beecount/web-features'

/** Display eligibility only. Native save validation and version checks still apply. */
export function canSummarizeOcrForm(form: TxForm) {
  return form.tx_type !== 'transfer' && /^\d+(?:\.\d{1,2})?$/.test(form.amount.trim())
    && Number(form.amount) > 0 && Boolean(form.account_name.trim()) && Boolean(form.category_name.trim())
    && Boolean(form.happened_at) && Number.isFinite(Date.parse(form.happened_at))
}

export function OcrReviewSummary({ form, onEdit }: { form: TxForm; onEdit: () => void }) {
  const income = form.tx_type === 'income'
  return <section aria-label="入账信息" className="mb-4 space-y-4 rounded-xl border border-border bg-muted/15 p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-sm text-muted-foreground">{income ? '收入' : '支出'}</p>
        <p className={`mt-1 text-3xl font-semibold tabular-nums ${income ? 'text-income' : 'text-expense'}`}>
          {income ? '+' : '−'}{(form.currency || 'CNY') === 'CNY' ? '¥' : `${form.currency} `}{Number(form.amount).toFixed(2)}
        </p>
      </div>
      <button type="button" className="min-h-11 shrink-0 rounded-lg px-2 text-sm font-medium underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={onEdit}>修改信息</button>
    </div>
    <p className="break-words text-sm font-medium">{form.note || '未填写备注'}</p>
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      <dt className="text-muted-foreground">账户</dt><dd className="break-words">{form.account_name}</dd>
      <dt className="text-muted-foreground">分类</dt><dd className="break-words">{form.category_name}</dd>
      <dt className="text-muted-foreground">账目时间</dt><dd className="break-words tabular-nums">{new Date(form.happened_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}（北京时间）</dd>
    </dl>
    <p className="text-xs leading-relaxed text-muted-foreground">{form.exclude_from_stats ? '暂不计入收支统计，可在修改信息中调整。' : '确认后计入收支统计。'}{form.exclude_from_budget ? '此笔不计入预算。' : ''}</p>
  </section>
}
