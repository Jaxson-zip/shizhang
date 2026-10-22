import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { fetchCaptureImage } from '../lib/ocr-inbox'

export function CapturePictureView({ imageUrl, loading, error }: { imageUrl?: string; loading?: boolean; error?: string }) {
  const [expanded, setExpanded] = useState(false)
  const [failedUrl, setFailedUrl] = useState('')
  useEffect(() => { setExpanded(false) }, [imageUrl])
  return <section aria-label="付款截图" className="rounded-xl border border-border bg-muted/20 p-3">
    {loading ? <p role="status" className="text-sm text-muted-foreground">正在读取付款截图…</p>
      : error || !imageUrl || failedUrl === imageUrl ? <p role="status" className="text-sm leading-relaxed text-muted-foreground">{error || '截图未上传或已清理，可继续手动核对账目。'}</p>
        : <button type="button" aria-label={expanded ? '收起付款截图大图' : '放大付款截图'} aria-expanded={expanded}
          onClick={() => setExpanded(value => !value)} className="block w-full rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <img src={imageUrl} alt="本次采集的付款截图" onError={() => setFailedUrl(imageUrl)}
            className={`mx-auto max-w-full rounded-lg object-contain ${expanded ? 'w-full cursor-zoom-out' : 'max-h-80 cursor-zoom-in'}`} />
          <span className="mt-2 block text-xs text-muted-foreground">{expanded ? '点击收起大图' : '点击图片放大核对'}</span>
        </button>}
  </section>
}

export function CapturePicture({ captureId }: { captureId: string }) {
  const { token } = useAuth()
  const key = `${token}:${captureId}`
  const [state, setState] = useState<{ key: string; imageUrl?: string; loading: boolean; error?: string }>({ key, loading: true })
  useEffect(() => {
    let disposed = false
    let objectUrl = ''
    setState({ key, loading: true })
    void fetchCaptureImage(token, captureId).then(blob => {
      if (disposed) return
      objectUrl = URL.createObjectURL(blob)
      setState({ key, loading: false, imageUrl: objectUrl })
    }).catch(() => {
      if (!disposed) setState({ key, loading: false, error: '截图未上传、已清理或暂时无法读取，可继续手动核对账目。' })
    })
    return () => { disposed = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [key, token, captureId])
  return state.key === key
    ? <CapturePictureView imageUrl={state.imageUrl} loading={state.loading} error={state.error} />
    : <CapturePictureView loading />
}
