import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'

import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Pagination,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useT
} from '@beecount/ui'

import type {
  AttachmentRef,
  ReadAccount,
  ReadCategory,
  ReadTag,
  ReadTransaction,
  WorkspaceCategory,
} from '@beecount/api-client'

import { TransactionAttachmentEditor, type TransactionAttachmentEditorHandle } from '../components/TransactionAttachmentEditor'
import { CurrencySelectorTrigger } from '../components/CurrencySelector'
import { CategoryPickerDialog } from '../components/CategoryPickerDialog'
import { CategoryIcon } from '../components/CategoryIcon'
import { TagPickerDialog } from '../components/TagPickerDialog'
import { TransactionList } from '../components/TransactionList'
import { useSingleFlight } from '../lib/singleFlight'
import { tagTextColorOn } from '../lib/tagColorPalette'
import { isTransactionAmountValid, setTransactionAdjustment, updateTransactionMagnitude } from '../lib/transactionAdjustment'
import type { TxForm } from '../forms'

type TransactionsPanelProps = {
  form: TxForm
  entryChoices?: { accountName?: string; categories: string[] }
  saveIssue?: string
  reviewNotice?: string
  reviewEvidence?: ReactNode
  reviewSummary?: ReactNode
  allowedTxTypes?: TxForm['tx_type'][]
  pendingSave?: { amount: number; currency?: string; accountName?: string; note?: string; happenedAt?: string; categoryName?: string; expired?: boolean } | null
  onRecoverSave?: () => Promise<boolean>
  /** Offered only once replaying the unconfirmed save is no longer safe. */
  onDiscardSave?: () => void
  /** 账本本位币(大写 ISO)。币种下拉默认值;选=本位币时 form.currency 存 ''。 */
  baseCurrency?: string
  /** v30 多币种:各币种对 baseCurrency 的汇率(1 quote ≈ x base),透传币种选择弹窗展示。 */
  currencyRates?: Record<string, number>
  rows: ReadTransaction[]
  total: number
  page: number
  pageSize: number
  accounts: ReadAccount[]
  categories: ReadCategory[]
  tags: ReadTag[]
  ledgerOptions: Array<{ ledger_id: string; ledger_name: string }>
  writeLedgerId: string
  onWriteLedgerIdChange: (ledgerId: string) => void
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
  canWrite: boolean
  dictionariesLoading?: boolean
  showCreatorColumn?: boolean
  showLedgerColumn?: boolean
  onFormChange: (next: TxForm) => void
  /** Dialog 显隐由外层控制。新建/编辑入口都靠 parent 在 setOpen(true) 之前
   *  把 form 初始化好,然后 setOpen(true)。这样 page 可以把"新建交易"按钮
   *  跟搜索/筛选放同一行,跟内嵌在 panel 内的 onCreate 解耦。 */
  dialogOpen: boolean
  onDialogOpenChange: (open: boolean) => void
  onSave: (attachments?: AttachmentRef[]) => Promise<boolean> | boolean
  onUploadAttachment: (file: File) => Promise<AttachmentRef>
  onReset: () => void
  onReload: () => void
  onPreviewAttachment: (
    refs: AttachmentRef[],
    startIndex: number
  ) => Promise<void>
  resolveAttachmentPreviewUrl: (ref: AttachmentRef) => Promise<string | null>
  /** 自定义分类图标的预签预览 URL 字典,TransactionList 里每行 CategoryIcon
   *  用来拿 blob URL 显示云端上传的 PNG 图标。material icon 不需要。 */
  iconPreviewUrlByFileId?: Record<string, string>
  onEdit: (row: ReadTransaction) => void
  onDelete: (row: ReadTransaction) => void
  /** 行整体点击 → 打开详情弹窗。如果不传则点行无效果(保留兼容性)。 */
  onSelect?: (row: ReadTransaction) => void
  /** dialogOnly:不渲染交易列表/分页,只挂编辑 Dialog + 内嵌 picker。
   *  让全局 edit 容器(GlobalEditTxDialog)能复用 panel 内置的所有字段渲染 +
   *  picker 联动逻辑,不必从头实现。 */
  dialogOnlyMode?: boolean
  /** 批量选择模式 —— 透传到 TransactionList。 */
  selectionMode?: boolean
  selectedIds?: Set<string>
  onToggleSelect?: (row: ReadTransaction, event: React.MouseEvent) => void
  /** §7 共享账本:开启后 tx 列表行末显示"谁记的"chip。 */
  showCreator?: boolean
  /** §7 共享账本:当前 caller user_id,自己创建+编辑的 tx 不显示 chip。 */
  currentUserId?: string | null
  /** 备注显示方式,透传到 TransactionList。默认 'category'。 */
  noteDisplayMode?: 'category' | 'note'
}

type AttachmentCarouselCellProps = {
  attachments: AttachmentRef[]
  onPreviewAttachment: (
    refs: AttachmentRef[],
    startIndex: number
  ) => Promise<void>
  resolveAttachmentPreviewUrl: (ref: AttachmentRef) => Promise<string | null>
  partialLabel: string
  metadataOnlyLabel: string
  notPreviewableLabel: string
  prevLabel: string
  nextLabel: string
}

function AttachmentCarouselCell({
  attachments,
  onPreviewAttachment,
  resolveAttachmentPreviewUrl,
  partialLabel,
  metadataOnlyLabel,
  notPreviewableLabel,
  prevLabel,
  nextLabel
}: AttachmentCarouselCellProps) {
  const [index, setIndex] = useState(0)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const readyAttachments = attachments.filter(
    (attachment) => typeof attachment.cloudFileId === 'string' && attachment.cloudFileId.trim().length > 0
  )
  const current = readyAttachments[index]

  useEffect(() => {
    if (readyAttachments.length === 0) {
      setIndex(0)
      return
    }
    if (index >= readyAttachments.length) {
      setIndex(0)
    }
  }, [index, readyAttachments.length])

  useEffect(() => {
    let cancelled = false
    if (!current) {
      setPreviewUrl(null)
      setLoading(false)
      return () => {
        cancelled = true
      }
    }
    setLoading(true)
    void resolveAttachmentPreviewUrl(current)
      .then((url) => {
        if (cancelled) return
        setPreviewUrl(url)
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [current, resolveAttachmentPreviewUrl])

  if (attachments.length === 0) return <>-</>

  if (readyAttachments.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="secondary">{attachments.length}</Badge>
        <span className="text-xs text-muted-foreground">{metadataOnlyLabel}</span>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="relative h-24 w-40 overflow-hidden rounded-md border border-border/70 bg-muted/30">
        {previewUrl ? (
          <img
            alt={current?.originalName || current?.fileName || 'attachment-preview'}
            className="h-full w-full cursor-zoom-in object-cover"
            src={previewUrl}
            onClick={() => {
              if (!current) return
              void onPreviewAttachment(readyAttachments, index)
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center px-2 text-center text-[11px] text-muted-foreground">
            {loading ? '...' : notPreviewableLabel}
          </div>
        )}
        {readyAttachments.length > 1 ? (
          <>
            <Button
              aria-label={prevLabel}
              className="absolute left-1 top-1/2 h-6 w-6 -translate-y-1/2 bg-background/90 p-0"
              size="icon"
              type="button"
              variant="outline"
              onClick={() =>
                setIndex((prev) => (prev - 1 + readyAttachments.length) % readyAttachments.length)
              }
            >
              ‹
            </Button>
            <Button
              aria-label={nextLabel}
              className="absolute right-1 top-1/2 h-6 w-6 -translate-y-1/2 bg-background/90 p-0"
              size="icon"
              type="button"
              variant="outline"
              onClick={() => setIndex((prev) => (prev + 1) % readyAttachments.length)}
            >
              ›
            </Button>
          </>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="default">{attachments.length}</Badge>
        {readyAttachments.length > 0 ? (
          <span className="text-xs text-muted-foreground">
            {Math.min(index + 1, readyAttachments.length)}/{readyAttachments.length}
          </span>
        ) : null}
        {readyAttachments.length < attachments.length ? (
          <span className="text-xs text-muted-foreground">{partialLabel}</span>
        ) : null}
      </div>
    </div>
  )
}

export function TransactionsPanel({
  form,
  entryChoices,
  baseCurrency = 'CNY',
  currencyRates,
  rows,
  total,
  page,
  pageSize,
  accounts,
  categories,
  tags,
  ledgerOptions,
  writeLedgerId,
  onWriteLedgerIdChange,
  onPageChange,
  onPageSizeChange,
  canWrite,
  dictionariesLoading = false,
  showCreatorColumn = false,
  showLedgerColumn = false,
  onFormChange,
  dialogOpen,
  onDialogOpenChange,
  saveIssue,
  reviewNotice,
  reviewEvidence,
  reviewSummary,
  allowedTxTypes,
  pendingSave,
  onRecoverSave,
  onDiscardSave,
  onSave,
  onUploadAttachment,
  onReset,
  onReload,
  onPreviewAttachment,
  resolveAttachmentPreviewUrl,
  iconPreviewUrlByFileId,
  onEdit,
  onDelete,
  onSelect,
  dialogOnlyMode,
  selectionMode = false,
  selectedIds,
  onToggleSelect,
  showCreator = false,
  currentUserId,
  noteDisplayMode = 'category'
}: TransactionsPanelProps) {
  const t = useT()
  const open = dialogOpen
  const inputId = useId()
  const setOpen = (next: boolean) => { if (!saving) onDialogOpenChange(next) }
  const [selectingImages, setSelectingImages] = useState(false)
  const attachmentEditor = useRef<TransactionAttachmentEditorHandle>(null)
  const [categoryPickerOpen, setCategoryPickerOpen] = useState(false)
  const [tagPickerOpen, setTagPickerOpen] = useState(false)
  // #450:保存是网络请求,请求返回前的连点会重复建交易 —— 单飞守卫 + 按钮禁用。
  const { saving, guard } = useSingleFlight()
  const saveButton = useRef<HTMLButtonElement>(null)
  const heading = useRef<HTMLSpanElement>(null)
  const appliedChoices = useRef('')
  useEffect(() => {
    if (!open) { appliedChoices.current = ''; return }
    if (form.editingId || pendingSave || dictionariesLoading) return
    const key = `${writeLedgerId}:${form.tx_type}`
    if (appliedChoices.current === key) return
    appliedChoices.current = key
    if (form.tx_type !== 'transfer' && !form.account_name && entryChoices?.accountName) {
      onFormChange({ ...form, account_name: entryChoices.accountName })
    }
  }, [open, writeLedgerId, form, pendingSave, dictionariesLoading, entryChoices, onFormChange])
  useEffect(() => {
    if (open && !saving && saveIssue) saveButton.current?.focus({ preventScroll: true })
  }, [open, saving, saveIssue])
  const textActionClass =
    'text-sm text-foreground underline-offset-4 hover:text-primary hover:underline disabled:pointer-events-none disabled:text-muted-foreground disabled:no-underline'
  const textDangerActionClass =
    'text-sm text-destructive underline-offset-4 hover:text-destructive/90 hover:underline disabled:pointer-events-none disabled:text-muted-foreground disabled:no-underline'

  const dedupSortNames = (names: string[]) =>
    names
      .filter((name) => name.length > 0)
      .filter((name, index, self) => self.indexOf(name) === index)
      .sort((a, b) => a.localeCompare(b))
  // 账户隐藏(issue #240):记账/转账选择器排除隐藏账户 —— 不能再往它记新账。
  const hiddenAccountNames = new Set(
    accounts.filter((row) => row.hidden).map((row) => row.name.trim())
  )
  const accountOptions = dedupSortNames(accounts.map((row) => row.name.trim()).filter((name) => !hiddenAccountNames.has(name)))
  // E1 唯一例外:编辑一笔本就挂在某隐藏账户上的历史交易时,选择器钉住显示该
  // 隐藏账户(带「已隐藏」灰标),让用户可原样保存;其它隐藏账户仍不出现。
  // 一旦改选走其它选项,该隐藏名字就不会再被钉回来(下次渲染 currentValue 已变)。
  const accountOptionsWithPinned = (currentValue: string) => {
    const trimmed = currentValue.trim()
    if (trimmed && hiddenAccountNames.has(trimmed)) {
      return dedupSortNames([...accountOptions, trimmed])
    }
    return accountOptions
  }
  const categoryOptions = categories
    .filter((row) => row.kind === form.tx_type)
    .map((row) => row.name.trim())
    .filter((name) => name.length > 0)
    .filter((name, index, self) => self.indexOf(name) === index)
    .sort((a, b) => a.localeCompare(b))
  // tag 选择改用 TagPickerDialog,组件自己做 dedup + 搜索 + chip 渲染,这里
  // 不再需要 tagOptions 派生(只保留 tagColorByName 给 trigger 按钮的小 chip
  // 渲染上色用)。
  // 按 name 反查 tag 颜色，tx 列表行里给每个标签 badge 上色。大小写不敏感。
  const tagColorByName = new Map<string, string>()
  for (const row of tags) {
    const key = (row.name || '').trim().toLowerCase()
    if (!key) continue
    if (row.color && !tagColorByName.has(key)) tagColorByName.set(key, row.color)
  }

  // 当前选中的分类 row(按 name + kind 反查),给 CategoryPicker 高亮 + 触发
  // 按钮显示图标。和 TransactionList 行内渲染保持同源。
  const selectedCategoryRow = useMemo<WorkspaceCategory | null>(() => {
    const name = (form.category_name || '').trim().toLowerCase()
    if (!name) return null
    return (
      (categories as WorkspaceCategory[]).find(
        (row) =>
          row.kind === form.tx_type &&
          (row.name || '').trim().toLowerCase() === name,
      ) ?? null
    )
  }, [categories, form.category_name, form.tx_type])

  const isTransfer = form.tx_type === 'transfer'
  // 非转账允许不选账户（与 mobile 保持一致，tx.accountId 本来就是 nullable）；
  // 转账必须两端都选（否则无法表达方向）。
  const canAdjust = !isTransfer && !allowedTxTypes
  const isAdjustment = canAdjust && form.amount.trim().startsWith('-')
  const canSubmit = Boolean(writeLedgerId.trim()) && isTransactionAmountValid(form.amount, form.tx_type, Boolean(allowedTxTypes)) && (isTransfer
    ? Boolean(form.from_account_name.trim()) && Boolean(form.to_account_name.trim())
    : Boolean(form.category_name.trim()))
  const selectedTags = form.tags
  const categoryValue = form.category_name.trim()

  const applyTxType = (nextType: TxForm['tx_type']) => {
    if (allowedTxTypes && !allowedTxTypes.includes(nextType)) return
    if (nextType === 'transfer') {
      // 转账两个标记都隐藏 → 清掉,避免残留脏值。
      // currency 一并清空:转账不支持跨币种且币种控件隐藏,不清会把转出/
      // 转入账户下拉锁死在之前手选的外币过滤里(审查发现)。
      onFormChange({
        ...form,
        amount: setTransactionAdjustment(form.amount, false),
        tx_type: nextType,
        account_name: '',
        currency: '',
        category_name: '',
        category_kind: 'transfer',
        exclude_from_stats: false,
        exclude_from_budget: false
      })
      return
    }
    const keepCategory = form.category_kind === nextType ? form.category_name : ''
    onFormChange({
      ...form,
      amount: nextType !== form.tx_type ? setTransactionAdjustment(form.amount, false) : form.amount,
      tx_type: nextType,
      category_kind: nextType,
      category_name: keepCategory,
      from_account_name: '',
      to_account_name: '',
      // 不计入预算仅 expense 显示;切到 income 时清掉
      exclude_from_budget: nextType === 'expense' ? form.exclude_from_budget : false
    })
  }

  const colCount = 8 + (showCreatorColumn ? 1 : 0) + (showLedgerColumn ? 1 : 0)

  return (
    <>
      {/* dialogOnlyMode: 全局编辑容器复用本 panel 的 Dialog + picker 联动,
          不渲染列表 / 分页。 */}
      {dialogOnlyMode ? null : (
        <div className="rounded-xl border border-border/50 bg-card">
          <TransactionList
            items={rows}
            tags={tags}
            categories={categories}
            iconPreviewUrlByFileId={iconPreviewUrlByFileId}
            variant="default"
            showCreator={showCreator}
            currentUserId={currentUserId}
            noteDisplayMode={noteDisplayMode}
            canManage={canWrite}
            onEdit={(row) => {
              onEdit(row)
              setOpen(true)
            }}
            onDelete={onDelete}
            onSelect={onSelect}
            onPreviewAttachment={onPreviewAttachment}
            resolveAttachmentPreviewUrl={resolveAttachmentPreviewUrl}
            selectionMode={selectionMode}
            selectedIds={selectedIds}
            onToggleSelect={onToggleSelect}
          />
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={onPageChange}
            onPageSizeChange={onPageSizeChange}
          />
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bc-manual-dialog flex max-h-[85vh] max-w-2xl flex-col gap-0 overflow-hidden p-0" onOpenAutoFocus={(event) => {
          if (window.matchMedia('(max-width: 639px)').matches) {
            event.preventDefault()
            heading.current?.focus({ preventScroll: true })
          }
        }}>
          <DialogHeader className="border-b border-border/60 px-6 py-4">
            <DialogTitle><span ref={heading} tabIndex={-1} className="outline-none">{reviewNotice ? t('ocrReview.title') : form.editingId ? t('transactions.button.update') : t('home.quickEntry')}</span></DialogTitle>
            <p className="truncate text-xs text-muted-foreground" title={ledgerOptions.find(row => row.ledger_id === writeLedgerId)?.ledger_name}>{ledgerOptions.find(row => row.ledger_id === writeLedgerId)?.ledger_name}</p>
          </DialogHeader>
          <div className="bc-manual-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-4">
            {reviewNotice && !pendingSave ? <p role="status" className="mb-4 rounded-xl border border-border bg-muted/30 p-3 text-sm leading-relaxed">{reviewNotice}</p> : null}
            {reviewEvidence && !pendingSave ? <div className="mb-4">{reviewEvidence}</div> : null}
            {reviewSummary && !pendingSave ? reviewSummary : null}
            {saveIssue ? <div role="alert" className="mb-4 space-y-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm leading-relaxed text-destructive">
              <p>{saveIssue}</p>
              {pendingSave ? <p className="font-medium">{pendingSave.currency || baseCurrency} {pendingSave.amount.toFixed(2)} · {pendingSave.accountName || t('transactions.placeholder.noAccount')}</p> : null}
              {pendingSave?.categoryName ? <p>{t('transactions.table.category')}：{pendingSave.categoryName}</p> : null}
              {pendingSave?.happenedAt ? <p>{t('transactions.table.time')}：{isoToDatetimeLocal(pendingSave.happenedAt).replace('T', ' ')}</p> : null}
              {pendingSave?.note ? <p className="break-words">{t('transactions.table.note')}：{pendingSave.note}</p> : null}
              {pendingSave?.expired && onDiscardSave ? <Button type="button" variant="outline" className="min-h-11 text-foreground" onClick={onDiscardSave}>{t('manual.discardExpired')}</Button> : null}
            </div> : null}
            <fieldset hidden={Boolean(pendingSave || reviewSummary)} disabled={saving || selectingImages || Boolean(pendingSave)} className={pendingSave || reviewSummary ? 'hidden' : 'grid gap-3 md:grid-cols-2'}>
              <div className="space-y-1 md:col-span-2">
                <Label htmlFor={`${inputId}-amount`}>{t('transactions.table.amount')}</Label>
                <div className="flex min-w-0 items-center gap-3 rounded-xl border border-input bg-muted/40 px-4 focus-within:ring-2 focus-within:ring-ring">
                  <span className="shrink-0 text-sm font-medium text-muted-foreground">{form.currency || baseCurrency}</span>
                  <Input id={`${inputId}-amount`} inputMode="decimal" enterKeyHint="done" autoComplete="off"
                    className="h-16 min-w-0 border-0 bg-transparent px-0 text-3xl font-semibold tabular-nums shadow-none focus-visible:ring-0 md:text-3xl"
                    placeholder="0.00" value={isAdjustment ? form.amount.trim().slice(1) : form.amount}
                    onChange={(e) => onFormChange({ ...form, amount: canAdjust ? updateTransactionMagnitude(form.amount, e.target.value) : e.target.value })} />
                </div>
                {canAdjust ? <div className="pt-2">
                  <label className="inline-flex min-h-11 cursor-pointer items-center gap-3 text-sm">
                    <input type="checkbox" className="h-5 w-5 accent-primary" checked={isAdjustment}
                      onChange={e => onFormChange({ ...form, amount: setTransactionAdjustment(form.amount, e.target.checked) })} />
                    {t(form.tx_type === 'expense' ? 'transactions.adjustment.expense' : 'transactions.adjustment.income')}
                  </label>
                  {isAdjustment ? <p className="text-sm text-muted-foreground">{t(form.tx_type === 'expense' ? 'transactions.adjustment.expenseHint' : 'transactions.adjustment.incomeHint')}</p> : null}
                </div> : null}
              </div>
              <div className={`grid ${allowedTxTypes?.length === 2 ? 'grid-cols-2' : 'grid-cols-3'} gap-1 rounded-xl bg-muted/60 p-1 md:col-span-2`} role="group" aria-label={t('transactions.table.type')}>
                {(['expense', 'income', 'transfer'] as const).filter(kind => !allowedTxTypes || allowedTxTypes.includes(kind)).map(kind => <button type="button" key={kind}
                  aria-pressed={form.tx_type === kind} onClick={() => applyTxType(kind)}
                  className={`min-h-11 rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${form.tx_type === kind ? 'bg-card text-primary shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
                  {t(`enum.txType.${kind}`)}
                </button>)}
              </div>
            <div className="space-y-1">
              <Label>{t('transactions.table.category')}</Label>
              {isTransfer ? (
                <Input disabled value={t('common.none')} />
              ) : (
                // 跟同行的 SelectTrigger 视觉对齐:h-10 + bg-muted + border-input,
                // 图标用 h-6 w-6 圆形塞得进 40px 高度,不撑大行高。
                <button
                  type="button"
                  disabled={dictionariesLoading}
                  onClick={() => setCategoryPickerOpen(true)}
                  className="flex h-10 w-full items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {selectedCategoryRow ? (
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15">
                      <CategoryIcon
                        icon={selectedCategoryRow.icon}
                        iconType={selectedCategoryRow.icon_type}
                        iconCloudFileId={selectedCategoryRow.icon_cloud_file_id}
                        iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                        size={16}
                        className="text-primary"
                      />
                    </span>
                  ) : null}
                  <span
                    className={`flex-1 truncate ${
                      categoryValue ? '' : 'text-muted-foreground'
                    }`}
                  >
                    {categoryValue || t('transactions.placeholder.categoryName')}
                  </span>
                  <span className="text-xs text-muted-foreground opacity-60">▾</span>
                </button>
              )}
            {!isTransfer && !form.editingId && (entryChoices?.categories.length || 0) > 0 ? (
              <div className="flex flex-wrap items-center gap-2 pt-2" role="group" aria-label={t('manual.recentCategories')}>
                <span className="text-xs text-muted-foreground">{t('manual.recentCategories')}</span>
                {entryChoices?.categories.map(name => <button type="button" key={name} disabled={dictionariesLoading}
                  onClick={() => onFormChange({ ...form, category_name: name, category_kind: form.tx_type })}
                  aria-pressed={form.category_name === name}
                  className="min-h-11 max-w-full break-words rounded-full border border-border bg-card px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-pressed:border-primary aria-pressed:text-primary">{name}</button>)}
              </div>
            ) : null}
            </div>
            {isTransfer ? (
              <>
                <div className="space-y-1">
                  <Label>{t('transactions.placeholder.fromAccountName')}</Label>
                  <Select
                    value={form.from_account_name || undefined}
                    disabled={dictionariesLoading}
                    onValueChange={(value) => onFormChange({ ...form, from_account_name: value })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('transactions.placeholder.fromAccountName')} />
                    </SelectTrigger>
                    <SelectContent>
                      {accountOptionsWithPinned(form.from_account_name).map((name) => (
                        <SelectItem key={name} value={name}>
                          {name}
                          {hiddenAccountNames.has(name) ? (
                            <span className="ml-1 text-xs text-muted-foreground">
                              {t('accounts.hidden.optionSuffix')}
                            </span>
                          ) : null}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t('transactions.placeholder.toAccountName')}</Label>
                  <Select
                    value={form.to_account_name || undefined}
                    disabled={dictionariesLoading}
                    onValueChange={(value) => onFormChange({ ...form, to_account_name: value })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('transactions.placeholder.toAccountName')} />
                    </SelectTrigger>
                    <SelectContent>
                      {accountOptionsWithPinned(form.to_account_name).map((name) => (
                        <SelectItem key={name} value={name}>
                          {name}
                          {hiddenAccountNames.has(name) ? (
                            <span className="ml-1 text-xs text-muted-foreground">
                              {t('accounts.hidden.optionSuffix')}
                            </span>
                          ) : null}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            ) : (
              <div className="space-y-1">
                <Label>{t('transactions.table.account')}</Label>
                <Select
                  // Radix SelectItem 不允许 value=""(undefined-state 由 placeholder
                  // 渲染),所以用 sentinel "__none__" 表示"不选账户"。和 form 的
                  // 真实空串状态在 value 和 onValueChange 两处来回翻译。
                  value={form.account_name ? form.account_name : '__none__'}
                  disabled={dictionariesLoading}
                  onValueChange={(value) =>
                    onFormChange({ ...form, account_name: value === '__none__' ? '' : value })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('transactions.placeholder.accountName')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">
                      <span className="text-muted-foreground">
                        {t('transactions.placeholder.noAccount')}
                      </span>
                    </SelectItem>
                    {accountOptionsWithPinned(form.account_name).map((name) => (
                      <SelectItem key={name} value={name}>
                        {name}
                        {hiddenAccountNames.has(name) ? (
                          <span className="ml-1 text-xs text-muted-foreground">
                            {t('accounts.hidden.optionSuffix')}
                          </span>
                        ) : null}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="space-y-1 md:col-span-2">
              <Label htmlFor={`${inputId}-note`}>{t('transactions.table.note')}</Label>
              <Input
                id={`${inputId}-note`}
                placeholder={t('transactions.placeholder.note')}
                value={form.note}
                onChange={(e) => onFormChange({ ...form, note: e.target.value })}
              />
            </div>
            <details open={reviewNotice && !form.happened_at ? true : undefined} key={`${writeLedgerId}:${form.editingId || 'new'}:${open}`} className="rounded-xl border border-border/60 bg-muted/15 md:col-span-2">
              <summary className="cursor-pointer rounded-xl px-3 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {t('manual.more')}
                <span className="mt-1 block text-xs font-normal leading-relaxed text-muted-foreground">
                  {isoToDatetimeLocal(form.happened_at).replace('T', ' ')} · {form.currency || baseCurrency}
                  {form.tags.length > 0 ? ` · ${form.tags.length} ${t('tags.title')}` : ''}
                  {(form.attachments?.length || 0) > 0 ? ` · ${form.attachments.length} ${t('manual.attachments')}` : ''}
                  {(form.exclude_from_stats || form.exclude_from_budget) ? ` · ${t('manual.flagsSet')}` : ''}
                </span>
              </summary>
              <div className="grid gap-3 border-t border-border/50 p-3 md:grid-cols-2">
              <div className="space-y-1">
              <Label>{t('shell.ledger')}</Label>
              <Select value={writeLedgerId || undefined} onValueChange={onWriteLedgerIdChange} disabled={Boolean(form.editingId) || saving}>
                <SelectTrigger>
                  <SelectValue placeholder={t('shell.ledger')} />
                </SelectTrigger>
                <SelectContent>
                  {ledgerOptions.map((ledger) => (
                    <SelectItem key={ledger.ledger_id} value={ledger.ledger_id}>
                      {ledger.ledger_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor={`${inputId}-time`}>{t('transactions.table.time')}</Label>
              <Input
                id={`${inputId}-time`}
                type="datetime-local"
                step={60}
                value={isoToDatetimeLocal(form.happened_at)}
                onChange={(e) =>
                  onFormChange({
                    ...form,
                    happened_at: datetimeLocalToIso(e.target.value, form.happened_at)
                  })
                }
              />
            </div>
                <div className="space-y-1">
                  <Label>{t('manual.currency')}</Label>
              {/* v30 多币种:币种另起一行,全宽显示币种全名+国旗(挨金额太窄会截断);
                  选非本位币 → 账户下拉按币种过滤 + 已选账户清空(币种优先联动,
                  transfer 不支持)。 */}
              {form.tx_type !== 'transfer' ? (
                <CurrencySelectorTrigger
                  value={form.currency || baseCurrency}
                  onChange={(code) =>
                    onFormChange({
                      ...form,
                      currency:
                        code.toUpperCase() === baseCurrency.toUpperCase()
                          ? ''
                          : code,
                      account_name: ''
                    })
                  }
                  ratesToBase={currencyRates}
                  rateBase={baseCurrency}
                />
              ) : null}                </div>
            <div className="space-y-1">
              <Label>{t('tags.title')}</Label>
              {/* tag 多选改用 TagPickerDialog —— mobile 风格的 chip 选择,带搜索
                  + 颜色块,比 DropdownMenu 直观。trigger 按钮里把已选标签缩略
                  显示成彩色 chip,空时占位文案。视觉上跟同行的 SelectTrigger 同高。 */}
              <button
                type="button"
                disabled={dictionariesLoading}
                onClick={() => setTagPickerOpen(true)}
                className="flex h-10 w-full items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="flex flex-1 items-center gap-1 overflow-hidden">
                  {selectedTags.length === 0 ? (
                    <span className="text-muted-foreground">
                      {t('common.none')}
                    </span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-1 overflow-hidden">
                      {selectedTags.slice(0, 3).map((name) => {
                        const color = tagColorByName.get(name.toLowerCase()) || '#94a3b8'
                        const fg = tagTextColorOn(color)
                        return (
                          <span
                            key={name}
                            className="inline-flex h-5 max-w-[120px] items-center rounded-full px-1.5 text-[11px] leading-none"
                            style={{ background: color, color: fg }}
                            title={name}
                          >
                            <span className="truncate">{name}</span>
                          </span>
                        )
                      })}
                      {selectedTags.length > 3 ? (
                        <span className="text-[11px] text-muted-foreground">
                          +{selectedTags.length - 3}
                        </span>
                      ) : null}
                    </span>
                  )}
                </span>
                <span className="text-xs text-muted-foreground opacity-60">▾</span>
              </button>
            </div>
            {/* §三 标记开关 — 按当前 type 条件显示:
                  不计入收支:income / expense(转账本就不进收支,隐藏)
                  不计入预算:仅 expense(预算只统计支出) */}
            {form.tx_type !== 'transfer' ? (
              <div className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2 md:col-span-2">
                <p className="text-sm font-medium">{t('txFlagExcludeFromStats')}</p>
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.exclude_from_stats}
                  aria-label={t('txFlagExcludeFromStats') as string}
                  onClick={() =>
                    onFormChange({ ...form, exclude_from_stats: !form.exclude_from_stats })
                  }
                  className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span aria-hidden className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${form.exclude_from_stats ? 'bg-primary' : 'bg-muted-foreground/30'}`}>
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                        form.exclude_from_stats ? 'translate-x-[18px]' : 'translate-x-0.5'
                      }`}
                    />
                  </span>
                </button>
              </div>
            ) : null}
            {form.tx_type === 'expense' ? (
              <div className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2 md:col-span-2">
                <p className="text-sm font-medium">{t('txFlagExcludeFromBudget')}</p>
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.exclude_from_budget}
                  aria-label={t('txFlagExcludeFromBudget') as string}
                  onClick={() =>
                    onFormChange({ ...form, exclude_from_budget: !form.exclude_from_budget })
                  }
                  className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span aria-hidden className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${form.exclude_from_budget ? 'bg-primary' : 'bg-muted-foreground/30'}`}>
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                        form.exclude_from_budget ? 'translate-x-[18px]' : 'translate-x-0.5'
                      }`}
                    />
                  </span>
                </button>
              </div>
            ) : null}
            {open ? <TransactionAttachmentEditor
              key={`${writeLedgerId}:${form.editingId || 'new'}`}
              ref={attachmentEditor}
              attachments={form.attachments}
              disabled={!canWrite || saving || selectingImages || !writeLedgerId}
              onSelectingChange={setSelectingImages}
              upload={onUploadAttachment}
              resolvePreview={resolveAttachmentPreviewUrl}
            /> : null}
              </div>
            </details>
          </fieldset>
          </div>
          <DialogFooter className="shrink-0 border-t border-border/60 bg-card px-6 py-4">
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => {
                onReset()
                setOpen(false)
              }}
            >
              {t('dialog.cancel')}
            </Button>
            <Button
              ref={saveButton}
              disabled={!canWrite || (!pendingSave && !canSubmit) || Boolean(pendingSave?.expired) || saving || selectingImages}
              onClick={() =>
                guard(async () => {
                  if (pendingSave) {
                    if (await onRecoverSave?.()) onDialogOpenChange(false)
                    return
                  }
                  const refs = await attachmentEditor.current?.prepare()
                  if (!refs) return
                  const success = await onSave(refs)
                  if (success) {
                    onDialogOpenChange(false)
                  }
                })
              }
            >
              {saving ? t('manual.saving') : pendingSave ? t('manual.recover') : reviewNotice ? t('ocrReview.save') : form.editingId ? t('transactions.button.update') : t('transactions.button.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 标签 picker —— chip 多选,跟 TagsPanel 卡片视觉一致。 */}
      <TagPickerDialog
        open={tagPickerOpen}
        onClose={() => setTagPickerOpen(false)}
        tags={tags}
        selectedNames={selectedTags}
        onChange={(names) => onFormChange({ ...form, tags: names })}
        onClearAll={() => onFormChange({ ...form, tags: [] })}
      />

      {/* 分类 picker —— 跟 mobile category_selector_dialog 同样的网格 + 子级
          展开交互。expense / income 切换跟随 form.tx_type;转账类型不开 picker。
          移除"未分类"footer —— 非转账交易必选分类(对齐 mobile transaction_editor_page,
          page 层 onSaveTransaction 也会再 guard 一次)。 */}
      <CategoryPickerDialog
        open={categoryPickerOpen}
        onClose={() => setCategoryPickerOpen(false)}
        kind={form.tx_type === 'income' ? 'income' : 'expense'}
        rows={categories as WorkspaceCategory[]}
        iconPreviewUrlByFileId={iconPreviewUrlByFileId}
        selectedId={selectedCategoryRow?.id}
        title={t('transactions.placeholder.categoryName')}
        onSelect={(cat) => {
          onFormChange({
            ...form,
            category_name: cat.name.trim(),
            category_kind: form.tx_type,
          })
        }}
      />
    </>
  )
}

/**
 * 把后端 ISO 时间（可能带 Z / 毫秒 / 时区 offset）转成 `<input type="datetime-local">`
 * 期望的 `YYYY-MM-DDTHH:mm` 字符串。用本地时区展示，避免用户看到的时间跟记录
 * 时间错位一个时区。
 */
function isoToDatetimeLocal(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * datetime-local 返回的本地时间字符串反序列化成后端想要的 ISO。保留原 value
 * 的秒与时区（避免用户只改了分钟却把秒抹 0 + 跨时区）。
 */
function datetimeLocalToIso(local: string, fallback: string): string {
  if (!local) return fallback
  // `new Date('2026-04-17T23:32')` 会按本地时区解析；toISOString() 再转 UTC。
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return fallback
  return d.toISOString()
}
