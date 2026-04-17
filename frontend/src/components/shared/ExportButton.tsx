import { useState, useMemo } from 'react'
import clsx from 'clsx'
import { useToast } from '../../hooks/useToast'
import ExportDialog, { type ExportType } from './ExportDialog'

interface ExportButtonProps {
  url: string
  label?: string
  filename?: string
  exportType?: ExportType
}

export default function ExportButton({ url, label = 'PNG', filename = 'export.png', exportType }: ExportButtonProps) {
  const [loading, setLoading] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const { toast } = useToast()

  // Parse URL into baseUrl + baseParams for the dialog
  const { baseUrl, baseParams } = useMemo(() => {
    const qIdx = url.indexOf('?')
    if (qIdx === -1) return { baseUrl: url, baseParams: {} as Record<string, string> }
    const base = url.slice(0, qIdx)
    const params: Record<string, string> = {}
    new URLSearchParams(url.slice(qIdx + 1)).forEach((v, k) => {
      params[k] = v
    })
    return { baseUrl: base, baseParams: params }
  }, [url])

  async function handleExport() {
    if (exportType) {
      setDialogOpen(true)
      return
    }

    setLoading(true)
    try {
      const response = await fetch(url)
      if (!response.ok) {
        let msg = 'Export failed'
        try {
          const body = await response.json()
          if (body?.detail) msg = String(body.detail)
        } catch { /* not JSON */ }
        toast(msg, 'error')
        return
      }
      const blob = await response.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename
      link.click()
      URL.revokeObjectURL(link.href)
      toast('Export downloaded', 'success')
    } catch {
      toast('Export failed', 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <button
        onClick={handleExport}
        disabled={loading}
        className={clsx(
          'btn inline-flex items-center gap-1.5 !text-[10px] uppercase',
          loading && 'opacity-50',
        )}
        style={{ letterSpacing: '0.15em' }}
        aria-label={loading ? 'Exporting' : `Export ${label}`}
      >
        {loading ? (
          <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        ) : (
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 1v9M4 7l4 4 4-4M2 13h12" />
          </svg>
        )}
        <span className="font-semibold">
          {loading ? 'Exporting' : label}
        </span>
      </button>
      {exportType && (
        <ExportDialog
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
          baseUrl={baseUrl}
          baseParams={baseParams}
          defaultFilename={filename}
          exportType={exportType}
        />
      )}
    </>
  )
}
