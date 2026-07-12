import type { ToastType } from '../../hooks/toastContext'

/** Extract FastAPI's JSON `detail` field from an error response, falling back to `fallback`. */
export async function parseFastApiError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (body?.detail) return String(body.detail)
  } catch { /* not JSON */ }
  return fallback
}

/** Fetch `url` and trigger a browser download as `filename`, reporting the
 *  outcome via toasts. Returns true on success; never throws. */
export async function downloadWithToast(
  url: string,
  filename: string,
  toast: (message: string, type?: ToastType) => void,
): Promise<boolean> {
  try {
    const response = await fetch(url)
    if (!response.ok) {
      toast(await parseFastApiError(response, 'Export failed'), 'error')
      return false
    }
    const blob = await response.blob()
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = filename
    link.click()
    URL.revokeObjectURL(link.href)
    toast('Export downloaded', 'success')
    return true
  } catch {
    toast('Export failed', 'error')
    return false
  }
}
