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

export default function ExportButton({ url, label = 'Export to PNG', filename = 'export.png', exportType }: ExportButtonProps) {
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
      if (!response.ok) throw new Error('Export failed')
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
        className={clsx('btn', loading && 'opacity-50')}
      >
        {loading ? 'Exporting...' : label}
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
