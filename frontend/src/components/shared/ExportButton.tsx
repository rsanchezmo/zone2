import { useState } from 'react'
import clsx from 'clsx'
import { useToast } from '../../hooks/useToast'
import ExportDialog, { type ExportType } from './ExportDialog'
import { downloadWithToast } from './download'

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
  const qIdx = url.indexOf('?')
  const baseUrl = qIdx === -1 ? url : url.slice(0, qIdx)
  const baseParams: Record<string, string> =
    qIdx === -1 ? {} : Object.fromEntries(new URLSearchParams(url.slice(qIdx + 1)))

  async function handleExport() {
    if (exportType) {
      setDialogOpen(true)
      return
    }

    setLoading(true)
    await downloadWithToast(url, filename, toast)
    setLoading(false)
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
