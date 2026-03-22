import { useState } from 'react'
import clsx from 'clsx'
import { useToast } from '../../hooks/useToast'

interface ExportButtonProps {
  url: string
  label?: string
  filename?: string
}

export default function ExportButton({ url, label = 'Export to PNG', filename = 'export.png' }: ExportButtonProps) {
  const [loading, setLoading] = useState(false)
  const { toast } = useToast()

  async function handleExport() {
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
    <button
      onClick={handleExport}
      disabled={loading}
      className={clsx('btn', loading && 'opacity-50')}
    >
      {loading ? 'Exporting...' : label}
    </button>
  )
}
