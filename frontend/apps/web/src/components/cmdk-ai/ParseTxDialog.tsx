import { type CSSProperties, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ExternalLink,
  Image as ImageIcon,
  Loader2,
  RotateCw,
  Sparkles,
  Send,
  X,
} from 'lucide-react'

import {
  type ApiError,
  type TxDraft,
  parseTxImage,
  parseTxText,
} from '@beecount/api-client'
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Textarea,
  useLocale,
  useT,
} from '@beecount/ui'

import { useAuth } from '../../context/AuthContext'
import { useLedgers } from '../../context/LedgersContext'
import { type DialogViewport, observeDialogViewport } from '../../lib/dialog-viewport'
import { readOcrPreferences } from '../../lib/ocr-preferences'
import { TxDraftList } from './TxDraftList'

type Mode = 'image' | 'text'
type Status = 'idle' | 'parsing' | 'parsed' | 'error' | 'fallback'
type FallbackKind =
  | 'no-vision-provider'   // B2 没绑 vision → 引导去 mobile 配
  | 'no-chat-provider'     // B3 没绑 chat
  | 'unknown'

export type ParseTxDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 由 GlobalParseTxDialog 通过事件传入 — 'image' 模式给 image blob,'text' 模式给文本 */
  initialMode: Mode
  initialImage?: Blob | null
  initialText?: string
}

/**
 * B2 / B3 共用 Dialog —— 上方显示原始输入(图片缩略图 / 文本 textarea),
 * 中间显示解析状态/结果,内嵌 TxDraftList 做编辑+保存。
 *
 * 设计:
 * - .docs/web-cmdk-ai-paste-screenshot.md
 * - .docs/web-cmdk-ai-paste-text.md
 */
export function ParseTxDialog({
  open,
  onOpenChange,
  initialMode,
  initialImage,
  initialText,
}: ParseTxDialogProps) {
  const t = useT()
  const { locale } = useLocale()
  const { token, profileMe } = useAuth()
  const { activeLedgerId } = useLedgers()

  const [mode, setMode] = useState<Mode>(initialMode)
  const [imageBlob, setImageBlob] = useState<Blob | null>(initialImage || null)
  const [imageUrl, setImageUrl] = useState<string>('')
  const [text, setText] = useState<string>(initialText || '')
  const [drafts, setDrafts] = useState<TxDraft[]>([])
  const [imageId, setImageId] = useState<string | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [fallback, setFallback] = useState<FallbackKind | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [errorRaw, setErrorRaw] = useState<string | null>(null)
  const [textEngine, setTextEngine] = useState<'rules' | 'ai'>('rules')
  const [campusTopupAsExpense, setCampusTopupAsExpense] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])
  const [viewport, setViewport] = useState<DialogViewport | null>(null)
  const cancelRef = useRef(false)

  useEffect(() => {
    if (!open) return
    return observeDialogViewport(window, setViewport)
  }, [open])

  useEffect(() => {
    if (!open) return
    setCampusTopupAsExpense(readOcrPreferences(profileMe?.ai_config, activeLedgerId || '').campus_topup_as_expense)
  }, [open, activeLedgerId, profileMe])

  // 同步外部 props(Dialog 重新打开时)
  useEffect(() => {
    if (!open) return
    setMode(initialMode)
    setImageBlob(initialImage || null)
    setText(initialText || '')
    setDrafts([])
    setImageId(null)
    setStatus('idle')
    setFallback(null)
    setErrorMsg(null)
    setErrorRaw(null)
    setTextEngine('rules')
    setWarnings([])
    cancelRef.current = false
  }, [open, initialMode, initialImage, initialText])

  // 关闭时清理 object url
  useEffect(() => {
    if (!imageBlob) {
      setImageUrl('')
      return
    }
    const url = URL.createObjectURL(imageBlob)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [imageBlob])

  // Only supplied OCR text may start automatically, using local-server rules.
  // Images and AI text require an explicit click after the upload/cost notice.
  useEffect(() => {
    if (!open || status !== 'idle' || initialMode !== 'text') return
    if (mode === 'text' && textEngine === 'rules' && text === initialText && text.trim()) {
      void runParse()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, initialMode, initialText])

  const runParse = async () => {
    if (!activeLedgerId) {
      setStatus('error')
      setErrorMsg(t('cmdk.parseTx.noLedger'))
      return
    }
    cancelRef.current = false
    setStatus('parsing')
    setErrorMsg(null)
    setWarnings([])
    setFallback(null)
    try {
      if (mode === 'image' && imageBlob) {
        const result = await parseTxImage(token, {
          image: imageBlob,
          ledgerId: activeLedgerId,
          locale,
        })
        if (cancelRef.current) return
        setDrafts(result.tx_drafts)
        setImageId(result.image_id)
        setStatus('parsed')
      } else if (mode === 'text' && text.trim()) {
        const result = await parseTxText(token, {
          text: text.trim(),
          ledgerId: activeLedgerId,
          locale,
          engine: textEngine,
          campusTopupAsExpense,
        })
        if (cancelRef.current) return
        setDrafts(result.tx_drafts)
        setWarnings(result.warnings || [])
        setStatus('parsed')
      } else {
        setStatus('idle')
      }
    } catch (err) {
      if (cancelRef.current) return
      const apiErr = err as ApiError
      if (apiErr.code === 'AI_NO_VISION_PROVIDER') {
        setStatus('fallback')
        setFallback('no-vision-provider')
      } else if (apiErr.code === 'AI_NO_CHAT_PROVIDER') {
        setStatus('fallback')
        setFallback('no-chat-provider')
      } else {
        setStatus('error')
        setErrorMsg(apiErr.message || String(err))
        setErrorRaw(apiErr.raw || null)
      }
    }
  }

  const handleSaved = () => {
    onOpenChange(false)
  }

  const titleIcon = mode === 'image' ? <ImageIcon className="h-4 w-4 text-primary" /> : <Sparkles className="h-4 w-4 text-primary" />
  const titleText = mode === 'image' ? t('cmdk.parseTx.dialogTitleImage') : t('cmdk.parseTx.dialogTitleText')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bc-parse-dialog flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"
        showCloseButton={false}
        fitViewport={false}
        style={viewport ? {
          '--ocr-view-height': `${viewport.height}px`,
          '--ocr-view-top': `${viewport.top}px`,
        } as CSSProperties : undefined}
      >
        <DialogHeader className="relative shrink-0 flex-row items-center gap-2 border-b border-border/40 p-4 pr-14">
          {titleIcon}
          <DialogTitle className="text-sm font-medium">{titleText}</DialogTitle>
          {status === 'parsed' && drafts.length > 0 && (
            <span className="ml-2 rounded-full border border-border/60 bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground">
              {t('cmdk.parseTx.recognizedCount', { count: drafts.length })}
            </span>
          )}
          <DialogClose className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={t('common.close')}>
            <X className="h-5 w-5" />
          </DialogClose>
        </DialogHeader>

        <div className="bc-parse-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {/* 原始输入展示区 */}
        {mode === 'image' && imageUrl && (
          <details className="border-b border-border/40 px-4 py-2">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              {t('cmdk.parseTx.viewImage')}
            </summary>
            <div className="mt-2">
              <img
                src={imageUrl}
                alt="screenshot"
                className="max-h-48 max-w-full rounded border border-border/40"
              />
            </div>
          </details>
        )}
        {mode === 'text' && (
          <details open={status !== 'parsed'} className="border-b border-border/40">
          <summary className="min-h-11 cursor-pointer px-4 py-3 text-sm text-muted-foreground">{t('ocrPreferences.source')}</summary>
          <div className="p-3 pt-0">
            <label className="mb-2 flex flex-wrap items-center gap-2 text-xs">
              {t('cmdk.parseTx.engineLabel')}
              <select
                className="min-h-10 rounded border border-border bg-background px-2 text-base md:text-sm"
                value={textEngine}
                disabled={status === 'parsing'}
                onChange={(e) => {
                  setTextEngine(e.target.value as 'rules' | 'ai')
                  setDrafts([])
                  setWarnings([])
                  setStatus('idle')
                }}
              >
                <option value="rules">{t('cmdk.parseTx.rulesEngine')}</option>
                <option value="ai">{t('cmdk.parseTx.aiEngine')}</option>
              </select>
            </label>
            {textEngine === 'rules' && (
              <>
                <p className="mb-2 text-xs leading-relaxed text-muted-foreground">{t('cmdk.parseTx.rulesHint')}</p>
                <a className="mb-2 inline-flex min-h-11 items-center text-sm text-primary underline" href="/app/settings/profile#ocr-preferences">{t('ocrPreferences.link')}</a>
                <label className="mb-2 flex min-h-11 cursor-pointer items-center gap-2 text-xs leading-relaxed">
                  <input
                    type="checkbox"
                    className="h-4 w-4 shrink-0 accent-primary"
                    checked={campusTopupAsExpense}
                    disabled={status === 'parsing'}
                    onChange={(e) => {
                      setCampusTopupAsExpense(e.target.checked)
                      setDrafts([])
                      setWarnings([])
                      setStatus('idle')
                    }}
                  />
                  {t('cmdk.parseTx.campusTopupAsExpense')}
                </label>
              </>
            )}
            {textEngine === 'ai' && (
              <p className="mb-3 text-sm leading-relaxed text-muted-foreground">{t('cmdk.parseTx.aiTextNotice')}</p>
            )}
            <Textarea
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setDrafts([])
                setWarnings([])
                setStatus('idle')
              }}
              placeholder={t(textEngine === 'rules' ? 'cmdk.parseTx.ocrPlaceholder' : 'cmdk.parseTx.textPlaceholder')}
              className="min-h-[80px] max-h-[200px] resize-y text-base md:text-[12px]"
              readOnly={status === 'parsing'}
            />
            {(status === 'idle' || status === 'parsed') && (
              <div className="mt-2 flex justify-end">
                <Button size="sm" onClick={runParse} disabled={!text.trim()}>
                  <Send className="mr-1 h-3 w-3" />
                  {status === 'parsed'
                    ? t('cmdk.parseTx.reparse')
                    : t(textEngine === 'ai' ? 'cmdk.parseTx.sendText' : 'cmdk.parseTx.parse')}
                </Button>
              </div>
            )}
          </div>
          </details>
        )}

        {/* 主体 */}
        <div className="px-4 py-3">
          {mode === 'image' && status !== 'parsed' && (
            <section className="mb-3 space-y-3 rounded-xl border border-border bg-muted/30 p-4">
              <h3 className="text-sm font-medium">{t('cmdk.parseTx.visionTitle')}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{t('cmdk.parseTx.visionNotice')}</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{t('cmdk.parseTx.freeOcrNotice')}</p>
              {status === 'idle' && (
                <Button className="min-h-11 w-full sm:w-auto" onClick={runParse} disabled={!imageBlob}>
                  <Send className="mr-2 h-4 w-4" />{t('cmdk.parseTx.sendImage')}
                </Button>
              )}
            </section>
          )}
          {warnings.length > 0 && (
            <div role="status" className="mb-3 rounded border border-border bg-muted/30 p-3 text-sm leading-relaxed">
              {warnings.map((warning) => <p key={warning}>{warning}</p>)}
            </div>
          )}
          {status === 'parsing' && (
            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <span className="text-xs">{t(mode === 'text' && textEngine === 'rules' ? 'cmdk.parseTx.rulesParsing' : 'cmdk.parseTx.parsing')}</span>
            </div>
          )}

          {status === 'fallback' && (
            <ParseTxFallback kind={fallback ?? 'unknown'} t={t} />
          )}

          {status === 'error' && errorMsg && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              <div className="mb-1 flex items-center gap-1.5 font-medium">
                <AlertTriangle className="h-3 w-3" />
                {t('cmdk.parseTx.error')}
              </div>
              <div className="break-words">{errorMsg}</div>
              {errorRaw && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[11px] opacity-80 hover:opacity-100">
                    {t('cmdk.parseTx.viewRaw')}
                  </summary>
                  <pre className="mt-1 max-h-48 overflow-auto rounded bg-background/60 p-2 text-[10px] font-mono whitespace-pre-wrap break-all">
                    {errorRaw}
                  </pre>
                </details>
              )}
              <Button variant="outline" size="sm" className="mt-2" onClick={runParse}>
                <RotateCw className="mr-1 h-3 w-3" />
                {t('cmdk.parseTx.retry')}
              </Button>
            </div>
          )}

          {status === 'parsed' && activeLedgerId && (
            <TxDraftList
              key={`${mode}-${textEngine}`}
              drafts={drafts}
              ledgerId={activeLedgerId}
              imageId={mode === 'image' ? imageId : null}
              extraTagName={
                mode === 'image' ? t('cmdk.parseTx.tagImage') : textEngine === 'rules' ? 'OCR' : t('cmdk.parseTx.tagText')
              }
              allowAiTag={mode === 'image' || textEngine === 'ai'}
              requireExplicitDetails={mode === 'text' && textEngine === 'rules'}
              locale={locale}
              onSaved={handleSaved}
              onCancel={() => onOpenChange(false)}
            />
          )}
        </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ────────────────────────────────────────────────────────────────────────
// Fallback panel — user 没绑对应 provider 时引导去 mobile 配
// ────────────────────────────────────────────────────────────────────────


type T = ReturnType<typeof useT>

function ParseTxFallback({ kind, t }: { kind: FallbackKind; t: T }) {
  let title = t('cmdk.parseTx.fallback.unknown.title')
  let body = t('cmdk.parseTx.fallback.unknown.body')
  if (kind === 'no-vision-provider') {
    title = t('cmdk.parseTx.fallback.noVision.title')
    body = t('cmdk.parseTx.fallback.noVision.body')
  } else if (kind === 'no-chat-provider') {
    title = t('cmdk.parseTx.fallback.noChat.title')
    body = t('cmdk.parseTx.fallback.noChat.body')
  }

  return (
    <div className="space-y-3 py-6">
      <div className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
        <AlertTriangle className="h-3.5 w-3.5" />
        <span className="font-medium">{title}</span>
      </div>
      <p className="text-sm text-muted-foreground">{body}</p>
      <a
        href="https://count.beejz.com/docs/ai/overview"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/40 px-3 py-1.5 text-xs font-medium hover:bg-muted"
      >
        <ExternalLink className="h-3 w-3" />
        {t('cmdk.parseTx.fallback.openDocs')}
      </a>
    </div>
  )
}
