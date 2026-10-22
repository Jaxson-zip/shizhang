import { FormEvent, useEffect, useState } from 'react'
import { HelpCircle } from 'lucide-react'

import {
  ApiError,
  detectWebClientInfo,
  getStoredDeviceId,
  login,
  verifyTwoFA
} from '@beecount/api-client'
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  LanguageToggle,
  ThemeToggle,
  useT
} from '@beecount/ui'
import { localizeError } from '../i18n/errors'

type LoginPageProps = {
  onLoggedIn: (token: string) => void
}

type ChallengeState = {
  challenge_token: string
  available_methods: Array<'totp' | 'recovery_code'>
}

export function LoginPage({ onLoggedIn }: LoginPageProps) {
  const t = useT()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState<{ type: 'default' | 'destructive'; title: string; message: string } | null>(null)
  const [challenge, setChallenge] = useState<ChallengeState | null>(null)
  const [aboutOpen, setAboutOpen] = useState(false)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    try {
      const data = await login(email, password)
      if (data.requires_2fa && data.challenge_token) {
        // 切到 2FA 输码视图,留住表单内容(用户失败重试时不必重输邮密)
        setChallenge({
          challenge_token: data.challenge_token,
          available_methods: data.available_methods || ['totp', 'recovery_code']
        })
        setNotice(null)
        return
      }
      if (data.access_token) {
        onLoggedIn(data.access_token)
        setNotice(null)
      }
    } catch (err) {
      const message = localizeError(err, t)
      if (err instanceof ApiError && err.code === 'AUTH_INVALID_CREDENTIALS') {
        setNotice({
          type: 'destructive',
          title: t('notice.failed'),
          message: t('login.error.invalid')
        })
        return
      }
      setNotice({
        type: 'destructive',
        title: t('notice.failed'),
        message
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="sz-login relative min-h-screen overflow-hidden bg-background text-foreground">
      <div className="sz-login-paper pointer-events-none absolute inset-0" aria-hidden />

      {/* 右上角工具栏 */}
      <div className="bc-login-tools absolute flex items-center gap-2">
        <LanguageToggle />
        <ThemeToggle />
      </div>

      <div className="bc-login-content relative mx-auto flex w-full max-w-6xl items-center justify-center">
        <div className="grid w-full gap-12 lg:grid-cols-[1fr_minmax(0,420px)] lg:items-center">
          {/* 左：品牌叙事 */}
          <div className="hidden max-w-xl space-y-8 lg:block">
            <div className="flex items-center gap-3">
              <img src="/branding/shizhang-art-v2-128.png" alt={t('shell.appName')} className="rounded-[24%] h-12 w-12" />
              <div>
                <div className="text-3xl font-semibold">{t('app.brand')}</div>
                <div className="text-sm text-muted-foreground">{t('app.subtitle')}</div>
              </div>
            </div>
            <h1 className="text-[40px] font-semibold leading-[1.4]">
              <span className="block text-primary">
                {t('login.heroHighlight')}
              </span>
              <span className="block">{t('login.heroTail')}</span>
            </h1>
            <p className="text-base text-muted-foreground">
              {t('login.subtitle')}
            </p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 text-sm leading-relaxed">
              <div className="border-l-2 border-primary/35 py-1 pl-4">
                <div className="font-semibold">{t('login.feature.syncTitle')}</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  {t('login.feature.syncDesc')}
                </div>
              </div>
              <div className="border-l-2 border-primary/35 py-1 pl-4">
                <div className="font-semibold">{t('login.feature.selfHostTitle')}</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  {t('login.feature.selfHostDesc')}
                </div>
              </div>
              <div className="border-l-2 border-primary/35 py-1 pl-4">
                <div className="font-semibold">{t('login.feature.multiTitle')}</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  {t('login.feature.multiDesc')}
                </div>
              </div>
              <div className="border-l-2 border-primary/35 py-1 pl-4">
                <div className="font-semibold">{t('login.feature.freeTitle')}</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  {t('login.feature.freeDesc')}
                </div>
              </div>
            </div>
          </div>

          {/* 右：登录表单卡 */}
          <div className="mx-auto w-full max-w-[420px]">
            <div className="sz-login-card rounded-3xl border border-border/70 bg-card p-6 shadow-[0_16px_60px_-40px_hsl(var(--foreground)/0.35)] sm:p-8">
              <div className="mb-6 flex items-center gap-3 lg:hidden">
                <img src="/branding/shizhang-art-v2-128.png" alt="" className="rounded-[24%] h-10 w-10" />
                <div>
                  <div className="text-lg font-bold">{t('app.brand')}</div>
                  <div className="text-xs text-muted-foreground">{t('app.subtitle')}</div>
                </div>
              </div>
              <div className="mb-6 space-y-1">
                <h2 className="text-2xl font-semibold">{t('login.title')}</h2>
                <p className="pt-1 text-sm leading-relaxed text-muted-foreground lg:hidden">{t('login.subtitle')}</p>
              </div>

              {challenge ? (
                <TwoFactorChallengeView
                  challenge={challenge}
                  onCancel={() => {
                    setChallenge(null)
                    setNotice(null)
                  }}
                  onVerified={(accessToken) => {
                    onLoggedIn(accessToken)
                  }}
                />
              ) : (
                <form className="space-y-5" onSubmit={onSubmit}>
                  <div className="space-y-1.5">
                    <Label className="inline-flex h-8 items-center" htmlFor="login-email">{t('login.email')}</Label>
                    <Input
                      id="login-email"
                      className="h-12 rounded-xl bg-card text-base md:text-base"
                      type="email"
                      inputMode="email"
                      autoCapitalize="none"
                      spellCheck={false}
                      autoComplete="email"
                      placeholder="owner@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex h-8 items-center justify-between gap-1.5">
                      <Label htmlFor="login-password">{t('login.password')}</Label>
                      {/* (?) 图标 hover 出 hint —— 即便用户关掉了下方提示卡,仍
                          能从这里查到初始密码出处。Tooltip 仅是 native title,
                          需要包裹 button(span 上的 title 在某些浏览器里 SVG
                          区域不触发 hover);同时点击 toggle 出可见浮窗作为
                          兜底,移动端 / 触屏没有 hover 时也能查看。 */}
                      <PasswordHintTrigger />
                    </div>
                    <Input
                      id="login-password"
                      className="h-12 rounded-xl bg-card text-base md:text-base"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>
                  <Button className="h-12 w-full rounded-xl text-base" type="submit" disabled={loading}>
                    {loading ? t('login.loading') : t('login.submit')}
                  </Button>
                </form>
              )}

              {notice && (
                <Alert className="mt-4" variant={notice.type}>
                  <AlertTitle>{notice.title}</AlertTitle>
                  <AlertDescription>{notice.message}</AlertDescription>
                </Alert>
              )}
            </div>
          </div>
        </div>
      </div>
      <footer className="sz-login-footer relative flex justify-center text-xs text-muted-foreground">
        <button type="button" className="min-h-11 rounded-lg px-3 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setAboutOpen(true)}>{t('about.title')}</button>
      </footer>
      <Dialog open={aboutOpen} onOpenChange={setAboutOpen}>
        <DialogContent className="w-[calc(100%-2rem)] max-w-sm">
          <DialogHeader><DialogTitle>{t('about.title')}</DialogTitle></DialogHeader>
          <img src="/branding/shizhang-art-v2-128.png" className="rounded-[24%] h-12 w-12" alt="" />
          <p className="text-sm leading-7">{t('about.brandDescription')}</p>
          <p className="text-xs leading-6 text-muted-foreground">{t('about.upstreamNotice')}</p>
          <a className="inline-flex min-h-11 items-center text-sm text-primary underline underline-offset-4" href="/upstream/NOTICE.txt" target="_blank" rel="noopener noreferrer">{t('about.licenseLink')}</a>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/**
 * (?) 图标 — hover 显示 native title;点击 toggle 一个临时浮窗,移动端没
 * hover 也能看;再点别处 / 自身关闭。比 Tooltip 组件可靠,因为后者只是 span
 * 的 title 在 SVG hit area 上某些浏览器不一定触发。
 */
function PasswordHintTrigger() {
  const t = useT()
  const [open, setOpen] = useState(false)
  const hint = t('login.initialPasswordHint') as string

  // 点弹窗外部 / Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onDoc = () => setOpen(false)
    window.addEventListener('keydown', onKey)
    // 用 setTimeout + capture=false,避免本次点击直接被 onDoc 捕获关掉
    const tid = window.setTimeout(() => document.addEventListener('click', onDoc), 0)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('click', onDoc)
      window.clearTimeout(tid)
    }
  }, [open])

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        title={hint}
        aria-label={hint}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      {open ? (
        <span
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 top-full z-10 mt-1.5 w-[min(260px,calc(100vw-4rem))] rounded-xl border border-border/60 bg-popover px-3 py-2 text-sm leading-relaxed text-foreground shadow-lg"
        >
          {hint}
        </span>
      ) : null}
    </span>
  )
}

/**
 * 2FA challenge view - login 拿到 requires_2fa=true 后切到这个表单。
 *
 * 倒计时:5 分钟从 challenge_token 签发起算;到点提示用户重新登录(后端的
 * challenge_token 实际 exp 也是 5 分钟,这里只是 UI 提示,过期后 verify 会
 * 抛 401,我们 fallback 让用户重 login)。
 */
function TwoFactorChallengeView({
  challenge,
  onCancel,
  onVerified
}: {
  challenge: ChallengeState
  onCancel: () => void
  onVerified: (accessToken: string) => void
}) {
  const t = useT()
  const [method, setMethod] = useState<'totp' | 'recovery_code'>('totp')
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setErr(null)
    try {
      const data = await verifyTwoFA({
        challenge_token: challenge.challenge_token,
        method,
        code: code.trim().replace(/\s+/g, ''),
        device_id: getStoredDeviceId(),
        client_info: detectWebClientInfo()
      })
      if (data.access_token) {
        onVerified(data.access_token)
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : String(e)
      setErr(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <div className="space-y-1.5">
        <Label>{t('login.twofa.method')}</Label>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={method === 'totp' ? 'default' : 'outline'}
            onClick={() => {
              setMethod('totp')
              setCode('')
            }}
          >
            {t('login.twofa.methodTotp')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={method === 'recovery_code' ? 'default' : 'outline'}
            onClick={() => {
              setMethod('recovery_code')
              setCode('')
            }}
          >
            {t('login.twofa.methodRecovery')}
          </Button>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="login-2fa-code">
          {method === 'totp' ? t('login.twofa.totpLabel') : t('login.twofa.recoveryLabel')}
        </Label>
        <Input
          id="login-2fa-code"
          inputMode={method === 'totp' ? 'numeric' : 'text'}
          autoComplete="one-time-code"
          maxLength={method === 'totp' ? 6 : 16}
          placeholder={method === 'totp' ? '000000' : 'xxxx-xxxx'}
          value={code}
          onChange={(e) =>
            setCode(method === 'totp' ? e.target.value.replace(/\D/g, '') : e.target.value)
          }
          autoFocus
        />
      </div>
      {err && <p className="text-sm text-destructive">{err}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="outline" onClick={onCancel} className="flex-1">
          {t('common.cancel')}
        </Button>
        <Button
          type="submit"
          disabled={loading || (method === 'totp' ? code.length !== 6 : code.length < 6)}
          className="flex-1"
        >
          {loading ? '…' : t('login.twofa.submit')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('login.twofa.hint')}</p>
    </form>
  )
}
