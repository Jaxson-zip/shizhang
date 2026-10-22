import { useCallback, useEffect, useRef, useState } from 'react'

import {
  createCategory,
  fetchWorkspaceAccounts,
  fetchWorkspaceCategories,
  fetchWorkspaceTags,
  updateCategory,
  uploadAttachment,
  type AttachmentRef,
  type WorkspaceAccount,
  type WorkspaceCategory,
  type WorkspaceTag,
} from '@beecount/api-client'
import { useT, useToast } from '@beecount/ui'
import {
  resolveCurrencyFields,
  isTransactionAmountValid,
  loadRatesToBase,
  CategoriesPanel,
  categoryDefaults,
  TransactionsPanel,
  uploadTransactionImage,
  txDefaults,
  type CategoryForm,
  type TxForm,
} from '@beecount/web-features'

import { useManualTxWrite } from '../hooks/useManualTxWrite'
import { CapturePicture } from './CapturePicture'
import { OCR_INBOX_CHANGED } from '../lib/ocr-inbox'
import { defaultEntryCategory, legacyChannelAccount } from '../lib/ocr-preferences'

import { useLedgerWrite } from '../app/useLedgerWrite'
import { useAttachmentCache } from '../context/AttachmentCacheContext'
import { useAuth } from '../context/AuthContext'
import { useLedgers } from '../context/LedgersContext'
import { localizeError } from '../i18n/errors'
import { dispatchOpenNewTx, onOpenEditCategory, onOpenEditTx, onOpenNewTx, type CaptureEditContext } from '../lib/txDialogEvents'
import { consumeOcrReview, ocrReviewForm, ocrReviewTypes, ocrReviewTypeChange, OCR_REVIEW_EVENT, retainOcrReview, reviewStorage, type OcrReview } from '../lib/ocr-review'
import { canSummarizeOcrForm, OcrReviewSummary } from './OcrReviewSummary'

/**
 * 全局编辑容器 — 任何页都能触发交易/分类编辑弹窗,不需要 navigate 到对应
 * 管理页。复用 TransactionsPanel/CategoriesPanel 的 Dialog + picker
 * (传 dialogOnlyMode 跳过列表渲染)。
 *
 * 跟之前散在 *Page 各自管理 detail+edit dialog 不同,这里统一在 AppShell 顶层
 * 处理:
 *   - 监听 openEditTx / openEditCategory 全局事件
 *   - 按需 fetch 写权限的 ledger refs(accounts/categories/tags)
 *   - 调 create/updateTransaction API + 命中 useLedgerWrite 的 CAS 重试
 *   - 写成功后通过 SyncSocket bumpLedger 触发其它页 refresh
 *
 * 编辑分类暂时仍走 navigate 到 /app/categories(分类编辑表单依赖 inline form
 * 的 icon picker / parent picker,数据流复杂,后续单独再做全局化)。
 */
/** The entry write is settled; only marking the capture reviewed was refused. Close as saved, never resend. */
function settledWithoutCaptureReview(error: unknown) {
  if (!(error instanceof Error) || error.message !== 'SAVED_CAPTURE_UNCONFIRMED') return false
  window.dispatchEvent(new Event(OCR_INBOX_CHANGED))
  return true
}

/** Says which existing entry a capture review touches, so a confirmation is never read as a second booking. */
export function captureReviewNotice(entry: CaptureEditContext['entry']) {
  return (entry === 'provisional'
    ? '这笔已记为临时账目，暂不计收支统计。对照截图核对，确认后更新原账目，不会另记一笔。'
    : entry === 'counted' ? '这笔已入账。对照截图核对，保存会更新原账目，不会另记一笔。'
      : '这次采集尚未入账。对照截图核对，确认后只记这一笔。')
    + '需要调整再点“修改信息”；缺失的信息请先补全。'
}

export function GlobalEditDialogs({ ledgersReady = true }: { ledgersReady?: boolean }) {
  const t = useT()
  const toast = useToast()
  const { token, sessionUserId, profileMe } = useAuth()
  const { ledgers, currency, activeLedgerId } = useLedgers()
  const { previewMap: iconPreviewByFileId, resolvePreview } = useAttachmentCache()
  const { retryOnConflict, isWriteConflict } = useLedgerWrite()

  const manualWrite = useManualTxWrite()
  const pendingWriteKey = manualWrite.pending?.key || ''
  const editTxVersion = useRef<number | undefined>()
  const refsSequence = useRef(0)
  const [editTxOpen, setEditTxOpen] = useState(false)
  const [ocrReview, setOcrReview] = useState<OcrReview | null>(null)
  const [reviewEditing, setReviewEditing] = useState(false)
  useEffect(() => { setReviewEditing(false) }, [editTxOpen])
  const [ocrCapture, setOcrCapture] = useState<CaptureEditContext | null>(null)
  const [editTxForm, setEditTxForm] = useState<TxForm>(txDefaults())
  const [editTxLedgerId, setEditTxLedgerId] = useState('')
  const [editTxAccounts, setEditTxAccounts] = useState<WorkspaceAccount[]>([])
  const [editTxCategories, setEditTxCategories] = useState<WorkspaceCategory[]>([])
  const [editTxTags, setEditTxTags] = useState<WorkspaceTag[]>([])
  const [refsLoading, setRefsLoading] = useState(false)
  useEffect(() => {
    if (!editTxOpen || refsLoading || (editTxForm.editingId && !ocrCapture)) return
    setEditTxForm(form => {
      const category = defaultEntryCategory(profileMe?.ai_config, editTxLedgerId, form.tx_type, editTxCategories, form.category_name)
      const account = ocrCapture && form.tx_type !== 'transfer'
        ? legacyChannelAccount(profileMe?.ai_config, editTxLedgerId, editTxAccounts, form.account_name) : form.account_name
      return category === form.category_name && account === form.account_name ? form : { ...form, category_name: category, account_name: account }
    })
  }, [editTxOpen, refsLoading, editTxForm.editingId, editTxForm.tx_type, ocrCapture, profileMe, editTxLedgerId, editTxCategories, editTxAccounts])
  // v30 多币种:编辑交易时币种弹窗展示各币种对账本主币种的汇率。
  const editTxBase = (
    ledgers.find((l) => l.ledger_id === editTxLedgerId)?.currency || 'CNY'
  )
    .trim()
    .toUpperCase()
  const [editTxRates, setEditTxRates] = useState<Record<string, number>>({})
  useEffect(() => {
    if (!token || !editTxOpen) return
    let cancelled = false
    loadRatesToBase(token, editTxBase)
      .then((m) => {
        if (!cancelled) setEditTxRates(m)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [token, editTxOpen, editTxBase])

  // 分类编辑相关
  const [editCatOpen, setEditCatOpen] = useState(false)
  const [editCatForm, setEditCatForm] = useState<CategoryForm>(categoryDefaults())
  const [editCatLedgerId, setEditCatLedgerId] = useState('')
  const [editCatRows, setEditCatRows] = useState<WorkspaceCategory[]>([])

  const notifyError = useCallback(
    (err: unknown) => toast.error(localizeError(err, t), t('notice.error')),
    [toast, t],
  )
  const notifySuccess = useCallback(
    (msg: string) => toast.success(msg, t('notice.success')),
    [toast, t],
  )

  // 该 ledger 是否对当前用户可写 — 决定 panel 的 ledgerOptions 列表
  const writableLedgers = ledgers.filter(
    (l) => l.role === 'owner' || l.role === 'editor',
  )
  const ledgerOptions = writableLedgers.map((l) => ({
    ledger_id: l.ledger_id,
    ledger_name: l.ledger_name,
  }))

  const loadRefsForLedger = useCallback(
    async (ledgerId: string) => {
      if (!ledgerId) return false
      const request = ++refsSequence.current
      setRefsLoading(true)
      setEditTxAccounts([])
      setEditTxCategories([])
      setEditTxTags([])
      try {
        const [accts, cats, tagsList] = await Promise.all([
          fetchWorkspaceAccounts(token, { ledgerId, limit: 500 }),
          fetchWorkspaceCategories(token, { ledgerId, limit: 500 }),
          fetchWorkspaceTags(token, { ledgerId, limit: 500 }),
        ])
        if (request !== refsSequence.current) return false
        setEditTxAccounts(accts)
        setEditTxCategories(cats)
        setEditTxTags(tagsList)
        return true
      } catch (err) {
        if (request === refsSequence.current) notifyError(err)
        return false
      } finally {
        if (request === refsSequence.current) setRefsLoading(false)
      }
    },
    [token, notifyError],
  )

  // 监听全局 openEditTx 事件 — 任何页 dispatch 都会被这里接住
  // 先 await fetch refs 再 open dialog,避免下拉空数据闪现
  useEffect(() => {
    return onOpenEditTx(async (tx) => {
      setOcrReview(null)
      setOcrCapture(tx.ocrCapture || null)
      const ledgerId =
        tx.ledger_id || writableLedgers[0]?.ledger_id || ''
      manualWrite.clearIssue()
      editTxVersion.current = tx.entry_change_id ?? undefined
      setEditTxLedgerId(ledgerId)
      setEditTxForm({
        editingId: tx.id,
        editingOwnerUserId: tx.created_by_user_id || '',
        tx_type: tx.tx_type,
        amount: String(tx.amount),
        happened_at: tx.happened_at,
        // v30 多币种:回显该笔币种 + 原币种(提交时币种未变不发字段,金额
        // 变更折算由 server L14 隐含汇率联动,防快照漂移)
        currency: (tx.currency_code || '').toUpperCase(),
        original_currency: (tx.currency_code || '').toUpperCase(),
        note: tx.note || '',
        category_name: tx.category_name || '',
        category_kind: (tx.category_kind as TxForm['category_kind']) || 'expense',
        account_name: tx.account_name || '',
        from_account_name: tx.from_account_name || '',
        to_account_name: tx.to_account_name || '',
        tags:
          tx.tags_list && tx.tags_list.length > 0
            ? tx.tags_list
            : (tx.tags || '')
                .split(',')
                .map((s) => s.trim())
                .filter((s) => s.length > 0),
        attachments: Array.isArray(tx.attachments) ? tx.attachments : [],
        exclude_from_stats: tx.ocrCapture ? Boolean(tx.ocrCapture.form.exclude_from_stats) : Boolean(tx.exclude_from_stats),
        exclude_from_budget: tx.ocrCapture ? Boolean(tx.ocrCapture.form.exclude_from_budget) : Boolean(tx.exclude_from_budget),
      })
      // 等 refs 拉完再打开 dialog,确保 category/account/tag 下拉有数据
      if (await loadRefsForLedger(ledgerId)) setEditTxOpen(true)
    })
  }, [loadRefsForLedger, writableLedgers])

  // 监听全局 openNewTx 事件 — CmdK / CalendarPage / 任意页 dispatch 都接住,
  // 不再要求触发方先 navigate 到 transactions 再 dispatch。
  // prefill.happenedAt:CalendarPage 选中某日 + 点新增时填充;
  // prefill.ledgerId:CalendarPage 把当前账本带过来;CmdK 不传走 active ledger。
  useEffect(() => {
    return onOpenNewTx(async (prefill) => {
      const review = prefill?.ocrReview
      if (review && (review.user_id !== sessionUserId || Date.now() >= review.expires_at
        || !writableLedgers.some((l) => l.ledger_id === review.ledger_id))) {
        notifyError(new Error(t('ocrReview.invalid')))
        return
      }
      const ledgerId =
        prefill?.ledgerId ||
        (activeLedgerId &&
        writableLedgers.some((l) => l.ledger_id === activeLedgerId)
          ? activeLedgerId
          : writableLedgers[0]?.ledger_id) ||
        ''
      setEditTxLedgerId(ledgerId)
      setOcrReview(review || null)
      setOcrCapture(prefill?.ocrCapture || null)
      manualWrite.clearIssue()
      editTxVersion.current = undefined
      const defaults = txDefaults()
      setEditTxForm({
        ...defaults,
        happened_at: review ? review.happened_at : prefill?.happenedAt || defaults.happened_at,
        ...(review ? ocrReviewForm(review) : {}),
        ...(prefill?.ocrCapture?.form || {}),
      })
      if (await loadRefsForLedger(ledgerId)) {
        if (!review || Date.now() < review.expires_at) setEditTxOpen(true)
        else notifyError(new Error(t('ocrReview.invalid')))
      } else if (review) retainOcrReview(reviewStorage, review)
    })
  }, [loadRefsForLedger, writableLedgers, activeLedgerId, sessionUserId, notifyError, t])

  useEffect(() => {
    const receive = () => {
      if (!sessionUserId || editTxOpen) return
      try {
        const review = consumeOcrReview(reviewStorage, sessionUserId, ledgersReady ? ledgers : null)
        if (review && manualWrite.pending) {
          if (manualWrite.pending.requestKey !== review.review_id) retainOcrReview(reviewStorage, review)
          dispatchOpenNewTx()
        } else if (review) dispatchOpenNewTx({ ledgerId: review.ledger_id, ocrReview: review })
      } catch { notifyError(new Error(t('ocrReview.invalid'))) }
    }
    receive()
    window.addEventListener(OCR_REVIEW_EVENT, receive)
    return () => window.removeEventListener(OCR_REVIEW_EVENT, receive)
  }, [sessionUserId, ledgers, ledgersReady, editTxOpen, pendingWriteKey, notifyError, t])

  // ledger 切换(理论上编辑模式下 ledger 不可改,新建模式下才能切)
  const handleLedgerChange = useCallback(
    (ledgerId: string) => {
      if (ocrReview || ocrCapture) return
      manualWrite.clearIssue()
      setEditTxLedgerId(ledgerId)
      setEditTxForm((prev) => ({ ...prev, account_name: '', from_account_name: '', to_account_name: '',
        category_name: '', tags: [], currency: '' }))
      void loadRefsForLedger(ledgerId)
    },
    [loadRefsForLedger, ocrReview, ocrCapture],
  )

  const handleSaveTx = useCallback(async (attachments: AttachmentRef[] = editTxForm.attachments): Promise<boolean> => {
    if (ocrCapture?.allowedTypes && !ocrCapture.allowedTypes.includes(editTxForm.tx_type)) {
      notifyError(new Error(t('ocrReview.directionMismatch')))
      return false
    }
    if (ocrCapture && (!editTxForm.happened_at || !Number.isFinite(Date.parse(editTxForm.happened_at)))) {
      notifyError(new Error(t('ocrReview.timeRequired')))
      return false
    }
    if (ocrReview && Date.now() >= ocrReview.expires_at) {
      notifyError(new Error(t('ocrReview.invalid')))
      return false
    }
    if (ocrReview && !ocrReviewTypes(ocrReview).includes(editTxForm.tx_type)) {
      notifyError(new Error(t('ocrReview.directionMismatch')))
      return false
    }
    if (ocrReview && (!editTxForm.happened_at || !Number.isFinite(Date.parse(editTxForm.happened_at)))) {
      notifyError(new Error(t('ocrReview.timeRequired')))
      return false
    }
    if ((ocrReview || ocrCapture) && editTxForm.tx_type !== 'transfer' && editTxAccounts.filter(
      (account) => !account.hidden && account.name === editTxForm.account_name,
    ).length !== 1) {
      notifyError(new Error(t('ocrReview.accountRequired')))
      return false
    }
    const ledgerId = editTxLedgerId.trim()
    if (!ledgerId) {
      notifyError(new Error(t('transactions.error.ledgerRequired')))
      return false
    }
    const amountNum = Number((editTxForm.amount || '').toString().trim())
    if (!isTransactionAmountValid(amountNum, editTxForm.tx_type, Boolean(ocrReview || ocrCapture))) {
      notifyError(new Error(t('transactions.error.amountInvalid')))
      return false
    }
    if (editTxForm.tx_type !== 'transfer' && !editTxForm.category_name.trim()) {
      notifyError(new Error(t('transactions.error.categoryRequired')))
      return false
    }
    if (editTxForm.tx_type === 'transfer') {
      if (
        !editTxForm.from_account_name.trim() ||
        !editTxForm.to_account_name.trim()
      ) {
        notifyError(new Error(t('transactions.error.transferAccountsRequired')))
        return false
      }
      if (
        editTxForm.from_account_name.trim() ===
        editTxForm.to_account_name.trim()
      ) {
        notifyError(new Error(t('transactions.error.transferAccountsDifferent')))
        return false
      }
    }

    // v30 多币种:共享 helper(override 口径/编辑防漂移/改回本位币),与
    // TransactionsPage 提交完全同一实现。
    const ledgerBase = (
      ledgers.find((l) => l.ledger_id === ledgerId)?.currency || 'CNY'
    )
      .trim()
      .toUpperCase()
    const accountCurrencyOfForm = editTxAccounts
      .find((a) => (a.name || '').trim() === editTxForm.account_name.trim())
      ?.currency?.toUpperCase()
    const effCurrency = (
      editTxForm.currency ||
      (editTxForm.tx_type !== 'transfer' ? accountCurrencyOfForm : '') ||
      ledgerBase
    ).toUpperCase()
    let currencyFields: { currency_code?: string; native_amount?: number } = {}
    if (editTxForm.tx_type !== 'transfer') {
      try {
        const resolved = await resolveCurrencyFields({
          token,
          ledgerBase,
          currency: effCurrency,
          amount: amountNum,
          originalCurrency: editTxForm.editingId
            ? editTxForm.original_currency
            : undefined
        })
        if (resolved) currencyFields = resolved
      } catch {
        notifyError(new Error(t('transactions.error.rateMissing')))
        return false
      }
    }

    const payload = {
      tx_type: editTxForm.tx_type,
      amount: amountNum,
      happened_at: editTxForm.happened_at,
      note: editTxForm.note.trim() || null,
      category_name:
        editTxForm.tx_type === 'transfer'
          ? null
          : editTxForm.category_name.trim() || null,
      category_kind:
        editTxForm.tx_type === 'transfer' ? null : editTxForm.tx_type,
      account_name:
        editTxForm.tx_type === 'transfer'
          ? null
          : editTxForm.account_name.trim() || null,
      from_account_name:
        editTxForm.tx_type === 'transfer'
          ? editTxForm.from_account_name.trim()
          : null,
      to_account_name:
        editTxForm.tx_type === 'transfer'
          ? editTxForm.to_account_name.trim()
          : null,
      tags: editTxForm.tags.filter((s) => s.length > 0),
      attachments,
      // §三 标记按 type 条件落库:转账两者都置 false;收入只允许 stats;支出两者都允许。
      exclude_from_stats:
        editTxForm.tx_type === 'transfer' ? false : editTxForm.exclude_from_stats,
      exclude_from_budget:
        editTxForm.tx_type === 'expense' ? editTxForm.exclude_from_budget : false,
      ...currencyFields
    }

    try {
      const saved = await manualWrite.save({ ledgerId, editingId: editTxForm.editingId || undefined,
        expectedVersion: editTxVersion.current,
        requestKey: editTxForm.editingId ? undefined : ocrCapture?.requestKey || ocrReview?.review_id,
        captureId: ocrCapture?.id, payload })
      notifySuccess(t(saved.idempotency_replayed ? 'manual.confirmed' : editTxForm.editingId ? 'notice.txUpdated' : 'notice.txCreated'))
      return true
    } catch (err) {
      if (settledWithoutCaptureReview(err)) {
        toast.warning(manualWrite.messageFor(err))
        return true
      }
      notifyError(new Error(manualWrite.messageFor(err)))
      return false
    }
  }, [
    editTxLedgerId,
    editTxForm,
    ocrReview,
    ocrCapture,
    editTxAccounts,
    ledgers,
    manualWrite,
    token,
    retryOnConflict,
    isWriteConflict,
    t,
    notifyError,
    notifySuccess,
  ])

  void currency

  // ==================== 分类编辑 ====================

  // 监听 openEditCategory:cat 自带 ledger_id,把 form 填上 + 拉一遍 ledger 内
  // 所有 categories(给 parent picker 用) + 打开
  // 同样 await 后再 open,parent picker 要的数据先到位
  useEffect(() => {
    return onOpenEditCategory(async (cat) => {
      const ledgerId = cat.ledger_id || writableLedgers[0]?.ledger_id || ''
      setEditCatLedgerId(ledgerId)
      setEditCatForm({
        editingId: cat.id,
        editingOwnerUserId: cat.created_by_user_id || '',
        name: cat.name,
        kind: cat.kind,
        level: String(cat.level ?? ''),
        sort_order: String(cat.sort_order ?? ''),
        icon: cat.icon || '',
        icon_type: cat.icon_type || 'material',
        custom_icon_path: cat.custom_icon_path || '',
        icon_cloud_file_id: cat.icon_cloud_file_id || '',
        icon_cloud_sha256: cat.icon_cloud_sha256 || '',
        parent_name: cat.parent_name || '',
        parent_sync_id: cat.parent_sync_id || '',
      })
      try {
        const cats = await fetchWorkspaceCategories(token, { ledgerId, limit: 500 })
        setEditCatRows(cats)
      } catch {
        setEditCatRows([])
      }
      setEditCatOpen(true)
    })
  }, [token, writableLedgers])

  const handleSaveCat = useCallback(async (): Promise<boolean> => {
    const ledgerId = editCatLedgerId.trim()
    if (!ledgerId) {
      notifyError(new Error(t('shell.selectLedgerFirst')))
      return false
    }
    try {
      const payload = {
        name: editCatForm.name,
        kind: editCatForm.kind,
        level: editCatForm.level ? Number(editCatForm.level) : null,
        sort_order: editCatForm.sort_order ? Number(editCatForm.sort_order) : null,
        icon: editCatForm.icon || null,
        icon_type: editCatForm.icon_type || null,
        custom_icon_path: editCatForm.custom_icon_path || null,
        icon_cloud_file_id: editCatForm.icon_cloud_file_id || null,
        icon_cloud_sha256: editCatForm.icon_cloud_sha256 || null,
        parent_name: editCatForm.parent_name || null,
        parent_sync_id: editCatForm.parent_sync_id || null,
      }
      await retryOnConflict(ledgerId, (base) =>
        editCatForm.editingId
          ? updateCategory(token, ledgerId, editCatForm.editingId, base, payload)
          : createCategory(token, ledgerId, base, payload),
      )
      notifySuccess(
        editCatForm.editingId
          ? t('notice.categoryUpdated')
          : t('notice.categoryCreated'),
      )
      return true
    } catch (err) {
      notifyError(err)
      return false
    }
  }, [
    editCatLedgerId,
    editCatForm,
    token,
    retryOnConflict,
    t,
    notifyError,
    notifySuccess,
  ])

  return (
    <>
      <TransactionsPanel
      dialogOnlyMode
      baseCurrency={editTxBase}
      currencyRates={editTxRates}
      form={editTxForm}
      entryChoices={ocrReview || ocrCapture ? { categories: [] } : manualWrite.entryChoices(editTxLedgerId, editTxForm.tx_type, editTxAccounts, editTxCategories)}
      reviewEvidence={ocrCapture && editTxOpen ? <CapturePicture key={ocrCapture.id} captureId={ocrCapture.id} /> : undefined}
      reviewSummary={ocrCapture && !reviewEditing && canSummarizeOcrForm(editTxForm)
        ? <OcrReviewSummary form={editTxForm} onEdit={() => setReviewEditing(true)} /> : undefined}
      reviewNotice={ocrCapture ? captureReviewNotice(ocrCapture.entry) : ocrReview ? t(ocrReview.version === 2
        ? ocrReview.review_reason === 'personal_incoming' ? 'ocrReview.personalIncoming' : 'ocrReview.groupPayment'
        : 'ocrReview.notice') : undefined}
      allowedTxTypes={ocrCapture?.allowedTypes || (ocrReview ? ocrReviewTypes(ocrReview) : undefined)}
      saveIssue={manualWrite.issue}
      pendingSave={manualWrite.pending ? { amount: manualWrite.pending.payload.amount, currency: manualWrite.pending.payload.currency_code || editTxBase,
        accountName: manualWrite.pending.payload.account_name || [manualWrite.pending.payload.from_account_name, manualWrite.pending.payload.to_account_name].filter(Boolean).join(' → ') || undefined,
        note: manualWrite.pending.payload.note || undefined, happenedAt: manualWrite.pending.payload.happened_at,
        categoryName: manualWrite.pending.payload.category_name || undefined, expired: manualWrite.pendingExpired } : null}
      onDiscardSave={() => { manualWrite.discardExpired(); setEditTxOpen(false) }}
      onRecoverSave={async () => {
        try { await manualWrite.recover(); notifySuccess(t('manual.confirmed')); return true }
        catch (err) {
          if (settledWithoutCaptureReview(err)) { toast.warning(manualWrite.messageFor(err)); return true }
          notifyError(new Error(manualWrite.messageFor(err))); return false
        }
      }}
      rows={[]}
      total={0}
      page={1}
      pageSize={20}
      accounts={editTxAccounts.filter((a) => {
        // 币种优先联动:账户下拉只显示「表单所选币种(默认=账本主币种)」的
        // 账户,防止选出币种与账户不一致的组合(与 TransactionsPage 同规则)
        const wanted = (editTxForm.currency || editTxBase).toUpperCase()
        return ((a.currency || 'CNY').trim().toUpperCase()) === wanted
      })}
      categories={editTxCategories}
      tags={editTxTags}
      ledgerOptions={ocrReview || ocrCapture ? ledgerOptions.filter(l => l.ledger_id === editTxLedgerId) : ledgerOptions}
      writeLedgerId={editTxLedgerId}
      onWriteLedgerIdChange={handleLedgerChange}
      onPageChange={() => undefined}
      onPageSizeChange={() => undefined}
      canWrite
      dictionariesLoading={refsLoading}
      onFormChange={(next) => setEditTxForm(ocrReview ? ocrReviewTypeChange(ocrReview, editTxForm, next)
        : ocrCapture?.allowedTypes && (ocrCapture.form.tx_type === 'income' || ocrCapture.form.tx_type === 'expense')
          ? ocrReviewTypeChange({ version: 2, tx_type: ocrCapture.form.tx_type }, editTxForm, next) : next)}
      dialogOpen={editTxOpen}
      onDialogOpenChange={setEditTxOpen}
      onSave={handleSaveTx}
      onUploadAttachment={(file) => uploadTransactionImage(token, editTxLedgerId, file)}
      onReset={() => { setOcrReview(null); setOcrCapture(null); setEditTxForm(txDefaults()) }}
      onReload={() => undefined}
      onPreviewAttachment={async () => undefined}
      resolveAttachmentPreviewUrl={(ref) => resolvePreview(ref.cloudFileId || '')}
      iconPreviewUrlByFileId={iconPreviewByFileId}
      onEdit={() => undefined}
      onDelete={() => undefined}
    />
    <CategoriesPanel
      dialogOnlyMode
      form={editCatForm}
      rows={editCatRows}
      iconPreviewUrlByFileId={iconPreviewByFileId}
      canManage
      dialogOpen={editCatOpen}
      onDialogOpenChange={setEditCatOpen}
      onFormChange={setEditCatForm}
      onSave={handleSaveCat}
      onReset={() => setEditCatForm(categoryDefaults())}
      onEdit={() => undefined}
      onDelete={() => undefined}
      onUploadIcon={async (file) => {
        const ledgerId = editCatLedgerId.trim()
        if (!ledgerId) return null
        try {
          const out = await uploadAttachment(token, { ledger_id: ledgerId, file })
          return { fileId: out.file_id, sha256: out.sha256 }
        } catch (err) {
          notifyError(err)
          return null
        }
      }}
    />
    </>
  )
}
