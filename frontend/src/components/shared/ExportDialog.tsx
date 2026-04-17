import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { useToast } from '../../hooks/useToast'
import ColorPicker from './ColorPicker'

export type ExportType =
  | 'weekly-report'
  | 'year-in-sport'
  | 'activity'
  | 'thunderstorm-heatmap'
  | 'efficiency-factor'
  | 'performance-frontier'
  | 'activity-clock'

const QUALITY_OPTIONS = [
  { label: 'Standard', dpi: 150 },
  { label: 'High', dpi: 300 },
  { label: 'Ultra', dpi: 600 },
] as const

const DEFAULT_DPIS: Record<ExportType, number> = {
  'weekly-report': 300,
  'year-in-sport': 300,
  'activity': 300,
  'thunderstorm-heatmap': 600,
  'efficiency-factor': 600,
  'performance-frontier': 600,
  'activity-clock': 600,
}

const EXPORT_LABELS: Record<ExportType, string> = {
  'weekly-report': 'Weekly Report',
  'year-in-sport': 'Year in Sport',
  'activity': 'Activity',
  'thunderstorm-heatmap': 'Heatmap',
  'efficiency-factor': 'Efficiency Factor',
  'performance-frontier': 'Performance Frontier',
  'activity-clock': 'Activity Clock',
}

interface ExportDialogProps {
  open: boolean
  onClose: () => void
  baseUrl: string
  baseParams: Record<string, string>
  defaultFilename: string
  exportType: ExportType
}

export default function ExportDialog({
  open,
  onClose,
  baseUrl,
  baseParams,
  defaultFilename,
  exportType,
}: ExportDialogProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()

  const [neonColor, setNeonColor] = useState('#fc0101')
  const [filename, setFilename] = useState(defaultFilename)
  const [quality, setQuality] = useState<number>(DEFAULT_DPIS[exportType])
  const [title, setTitle] = useState('')
  const [showTitle, setShowTitle] = useState(true)
  const [radiusKm, setRadiusKm] = useState('20')
  const [downloading, setDownloading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewSrc, setPreviewSrc] = useState<string | null>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const previewCounter = useRef(0)

  // Reset state when dialog opens
  useEffect(() => {
    if (!open) return
    setNeonColor('#fc0101')
    setFilename(defaultFilename)
    setQuality(DEFAULT_DPIS[exportType])
    setTitle('')
    setShowTitle(true)
    setRadiusKm('20')
    setPreviewError(null)
    setPreviewSrc(null)
    setPreviewLoading(false)
    // Auto-generate initial preview. Cancel the rAF if the dialog closes
    // (or remounts) before it fires to avoid setState-after-unmount.
    const rafId = requestAnimationFrame(() => generatePreviewRef.current?.())
    return () => cancelAnimationFrame(rafId)
  }, [open, defaultFilename, exportType])

  // Build URL with given DPI
  const buildUrl = useCallback((dpi: number) => {
    const params = new URLSearchParams(baseParams)
    if (hasColorOption(exportType)) {
      params.set('neon_color', neonColor)
    }
    params.set('dpi', String(dpi))
    if (exportType === 'activity' && title) {
      params.set('title', title)
    }
    if (exportType === 'thunderstorm-heatmap') {
      if (radiusKm) params.set('radius_km', radiusKm)
      params.set('show_title', String(showTitle))
    }
    return `${baseUrl}?${params.toString()}`
  }, [baseUrl, baseParams, neonColor, title, radiusKm, showTitle, exportType])

  const generatePreview = useCallback(() => {
    const id = ++previewCounter.current
    const url = buildUrl(72)
    setPreviewLoading(true)
    setPreviewError(null)

    // Fetch instead of <img src> so we can read the server's error body
    // (FastAPI returns JSON with a `detail` field) and surface it to the user.
    let objectUrl: string | null = null
    fetch(url).then(async r => {
      if (id !== previewCounter.current) return
      if (!r.ok) {
        let msg = `Preview unavailable (${r.status})`
        try {
          const body = await r.json()
          if (body?.detail) msg = String(body.detail)
        } catch { /* not JSON */ }
        setPreviewError(msg)
        setPreviewLoading(false)
        return
      }
      const blob = await r.blob()
      if (id !== previewCounter.current) {
        URL.revokeObjectURL(URL.createObjectURL(blob))
        return
      }
      objectUrl = URL.createObjectURL(blob)
      setPreviewSrc(prev => {
        if (prev) URL.revokeObjectURL(prev)
        return objectUrl
      })
      setPreviewLoading(false)
    }).catch(() => {
      if (id !== previewCounter.current) return
      setPreviewError('Preview unavailable')
      setPreviewLoading(false)
    })
  }, [buildUrl])

  // Keep a ref so the reset effect can call the latest version
  const generatePreviewRef = useRef(generatePreview)
  generatePreviewRef.current = generatePreview

  // Escape key handler
  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  async function handleDownload() {
    setDownloading(true)
    try {
      const url = buildUrl(quality)
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
      onClose()
    } catch {
      toast('Export failed', 'error')
    } finally {
      setDownloading(false)
    }
  }

  if (!open) return null

  const colorOption = hasColorOption(exportType)

  return createPortal(
    <div
      className={clsx(
        'fixed inset-0 flex items-center justify-center z-[10001] animate-[fadeIn_150ms_ease-out]',
        isLight ? 'bg-black/30' : 'bg-black/60'
      )}
      onClick={onClose}
    >
      <div
        className={clsx(
          'border rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto',
          'animate-[scaleIn_150ms_ease-out]',
          isLight
            ? 'bg-white border-gray-200 shadow-xl'
            : 'bg-surface-800 border-surface-600 shadow-2xl'
        )}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className={clsx(
          'flex items-center justify-between px-5 py-4 border-b',
          isLight ? 'border-gray-100' : 'border-surface-600'
        )}>
          <div>
            <h3 className={clsx('text-sm font-semibold', isLight ? 'text-gray-800' : 'text-gray-100')}>
              Export Settings
            </h3>
            <p className={clsx('text-xs mt-0.5', isLight ? 'text-gray-400' : 'text-gray-500')}>
              {EXPORT_LABELS[exportType]}
            </p>
          </div>
          <button
            onClick={onClose}
            className={clsx(
              'w-7 h-7 rounded-md flex items-center justify-center transition-colors',
              isLight ? 'hover:bg-gray-100 text-gray-400' : 'hover:bg-surface-600 text-gray-500'
            )}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="px-5 py-4 flex flex-col gap-5">
          {/* Preview */}
          <div className={clsx(
            'relative rounded-lg overflow-hidden border',
            isLight ? 'border-gray-200 bg-gray-50' : 'border-surface-600 bg-surface-900'
          )}>
            <div className="relative flex items-center justify-center" style={{ minHeight: '180px', maxHeight: '420px' }}>
              {previewLoading && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className={clsx(
                    'flex flex-col items-center gap-3',
                    isLight ? 'text-gray-400' : 'text-gray-500'
                  )}>
                    <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    <span className="text-xs">Generating preview...</span>
                  </div>
                </div>
              )}
              {!previewSrc && !previewLoading && !previewError && (
                <div className={clsx(
                  'flex flex-col items-center gap-2 py-8',
                  isLight ? 'text-gray-400' : 'text-gray-500'
                )}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <path d="m21 15-5-5L5 21" />
                  </svg>
                  <span className="text-xs">Click refresh to generate preview</span>
                </div>
              )}
              {previewError && !previewLoading && (
                <div className={clsx(
                  'flex flex-col items-center gap-2 py-8 px-4 text-center',
                  isLight ? 'text-gray-400' : 'text-gray-500'
                )}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <path d="m21 15-5-5L5 21" />
                  </svg>
                  <span className="text-xs max-w-[28ch]">{previewError}</span>
                </div>
              )}
              {previewSrc && (
                <img
                  ref={imgRef}
                  src={previewSrc}
                  alt="Export preview"
                  className={clsx(
                    'max-h-[420px] w-auto max-w-full object-contain transition-opacity duration-200',
                    previewLoading ? 'opacity-40' : 'opacity-100'
                  )}
                />
              )}
            </div>
            {/* Refresh preview button */}
            <button
              onClick={generatePreview}
              disabled={previewLoading}
              className={clsx(
                'absolute top-2 right-2 w-7 h-7 rounded-md flex items-center justify-center transition-all',
                'backdrop-blur-sm border',
                previewLoading && 'opacity-50',
                isLight
                  ? 'bg-white/80 border-gray-200 text-gray-500 hover:bg-white hover:text-gray-700'
                  : 'bg-surface-800/80 border-surface-600 text-gray-400 hover:bg-surface-700 hover:text-gray-200'
              )}
              title="Refresh preview"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                className={previewLoading ? 'animate-spin' : ''}
              >
                <path d="M14 8A6 6 0 1 1 8 2" />
                <path d="M14 2v4h-4" />
              </svg>
            </button>
          </div>

          {/* Color picker */}
          {colorOption && (
            <Section label="Color" isLight={isLight}>
              <ColorPicker value={neonColor} onChange={setNeonColor} />
            </Section>
          )}

          {/* Quality */}
          <Section label="Quality" isLight={isLight}>
            <div className="flex gap-1">
              {QUALITY_OPTIONS.map(opt => (
                <button
                  key={opt.dpi}
                  className="chip"
                  data-active={quality === opt.dpi}
                  onClick={() => setQuality(opt.dpi)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </Section>

          {/* Filename */}
          <Section label="Filename" isLight={isLight}>
            <input
              type="text"
              value={filename}
              onChange={e => setFilename(e.target.value)}
              className="input w-full text-xs font-mono"
            />
          </Section>

          {/* Per-export: Title (activity) */}
          {exportType === 'activity' && (
            <Section label="Title" isLight={isLight}>
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="Custom title (optional)"
                className="input w-full text-xs"
              />
            </Section>
          )}

          {/* Per-export: Heatmap settings */}
          {exportType === 'thunderstorm-heatmap' && (
            <>
              <Section label="Radius (km)" isLight={isLight}>
                <input
                  type="number"
                  value={radiusKm}
                  onChange={e => setRadiusKm(e.target.value)}
                  min={1}
                  max={200}
                  className="input w-24 text-xs font-mono"
                />
              </Section>
              <div className="flex items-center justify-between">
                <label className={clsx('text-xs font-medium', isLight ? 'text-gray-500' : 'text-gray-400')}>
                  Show title
                </label>
                <button
                  onClick={() => setShowTitle(v => !v)}
                  className={clsx(
                    'relative inline-flex items-center w-10 h-[22px] rounded-full transition-colors duration-200 shrink-0',
                    showTitle
                      ? 'bg-blue-500'
                      : isLight ? 'bg-gray-300' : 'bg-surface-600'
                  )}
                >
                  <span className={clsx(
                    'inline-block w-[16px] h-[16px] rounded-full bg-white shadow-sm transition-transform duration-200',
                    showTitle ? 'translate-x-[21px]' : 'translate-x-[3px]'
                  )} />
                </button>
              </div>
            </>
          )}
        </div>

        {/* Footer actions */}
        <div className={clsx(
          'flex items-center justify-end gap-2 px-5 py-4 border-t',
          isLight ? 'border-gray-100' : 'border-surface-600'
        )}>
          <button onClick={onClose} className="btn">
            Cancel
          </button>
          <button
            onClick={handleDownload}
            disabled={downloading}
            className={clsx(
              'btn font-semibold',
              downloading && 'opacity-50'
            )}
            style={{
              borderColor: colorOption ? neonColor : undefined,
              color: colorOption ? neonColor : undefined,
              boxShadow: colorOption ? `0 0 12px ${neonColor}20` : undefined,
            }}
          >
            {downloading ? 'Exporting...' : 'Download'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

function hasColorOption(exportType: ExportType) {
  return !['efficiency-factor', 'performance-frontier'].includes(exportType)
}

function Section({ label, isLight, children }: { label: string; isLight: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className={clsx('text-xs font-medium', isLight ? 'text-gray-500' : 'text-gray-400')}>
        {label}
      </label>
      {children}
    </div>
  )
}
