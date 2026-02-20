import { useState } from 'react'
import clsx from 'clsx'

interface ExportButtonProps {
  url: string
  label?: string
  filename?: string
}

export default function ExportButton({ url, label = 'Export to PNG', filename = 'export.png' }: ExportButtonProps) {
  const [loading, setLoading] = useState(false)

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
    } catch (err) {
      console.error('Export error:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handleExport}
      disabled={loading}
      className={clsx(
        'px-3 py-1.5 rounded text-xs font-medium transition-colors',
        loading
          ? 'bg-surface-600 text-gray-500'
          : 'bg-neon-red/20 text-neon-red hover:bg-neon-red/30'
      )}
    >
      {loading ? 'Exporting...' : label}
    </button>
  )
}
