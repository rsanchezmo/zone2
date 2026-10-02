import { useState } from 'react'
import clsx from 'clsx'
import { useGeocodeCity, useSportTypes } from '../../api/hooks'
import { BACKDROP_MAX_OPACITY, BACKDROP_MIN_OPACITY } from '../../hooks/backdropContext'
import { useBackdrop } from '../../hooks/useBackdrop'
import { useTheme } from '../../hooks/useTheme'
import { useToast } from '../../hooks/useToast'
import ChartPanel from './ChartPanel'
import ColorPicker from './ColorPicker'

/** Configures the neon route wallpaper rendered behind every page. */
export default function BackdropSettingsPanel() {
  const { settings, update } = useBackdrop()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const { data: sportTypes } = useSportTypes()
  const geocode = useGeocodeCity()
  const [cityQuery, setCityQuery] = useState('')

  function handleResolveCity() {
    const query = cityQuery.trim()
    if (!query) return
    geocode.mutate(query, {
      onSuccess: result => {
        update({
          city: {
            name: result.display_name.split(',')[0].trim() || query,
            south: result.bbox.south,
            west: result.bbox.west,
            north: result.bbox.north,
            east: result.bbox.east,
          },
        })
        setCityQuery('')
        toast(`Backdrop framed on ${result.display_name}`, 'success')
      },
      onError: () => toast(`No place found for "${query}"`, 'error'),
    })
  }

  const mutedText = isLight ? 'text-gray-500' : 'text-gray-400'

  return (
    <ChartPanel
      title="Page background"
      accent={settings.color}
      toolbar={
        <button
          type="button"
          className="chip"
          data-active={settings.enabled}
          onClick={() => update({ enabled: !settings.enabled })}
        >
          {settings.enabled ? 'On' : 'Off'}
        </button>
      }
      footer={
        <p className={clsx('text-[11px] leading-relaxed', mutedText)}>
          Draws your routes as a faint neon wallpaper behind the app. Stored in this browser only.
        </p>
      }
    >
      <div className={clsx('space-y-4', !settings.enabled && 'opacity-50 pointer-events-none')}>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="eyebrow block mb-1.5">Sport</span>
            <select
              className="select w-full"
              value={settings.sport}
              onChange={e => update({ sport: e.target.value })}
            >
              <option value="">All sports</option>
              {sportTypes?.map(sport => (
                <option key={sport} value={sport}>{sport}</option>
              ))}
            </select>
          </label>

          <div>
            <span className="eyebrow block mb-1.5">City</span>
            {settings.city ? (
              <div className="flex items-center gap-2">
                <span className={clsx('text-sm truncate', isLight ? 'text-gray-700' : 'text-gray-200')}>
                  {settings.city.name}
                </span>
                <button type="button" className="btn text-xs ml-auto" onClick={() => update({ city: null })}>
                  Clear
                </button>
              </div>
            ) : (
              <div className="flex gap-2">
                <input
                  className="input flex-1 min-w-0"
                  placeholder="Madrid, Spain"
                  value={cityQuery}
                  onChange={e => setCityQuery(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleResolveCity()}
                />
                <button
                  type="button"
                  className="btn text-xs"
                  onClick={handleResolveCity}
                  disabled={geocode.isPending || !cityQuery.trim()}
                >
                  {geocode.isPending ? 'Finding…' : 'Set'}
                </button>
              </div>
            )}
            <p className={clsx('text-[11px] mt-1.5', mutedText)}>
              {settings.city ? 'Only routes inside this city are drawn.' : 'Leave empty to frame every route.'}
            </p>
          </div>
        </div>

        <div>
          <span className="eyebrow block mb-1.5">Color</span>
          <ColorPicker value={settings.color} onChange={hex => update({ color: hex })} />
        </div>

        <label className="block">
          <span className="eyebrow flex items-center justify-between mb-1.5">
            Intensity
            <span className="font-mono tabular-nums normal-case">{Math.round(settings.opacity * 100)}%</span>
          </span>
          <input
            type="range"
            className="w-full h-6 md:h-4 accent-current"
            style={{ color: settings.color }}
            min={BACKDROP_MIN_OPACITY * 100}
            max={BACKDROP_MAX_OPACITY * 100}
            step={1}
            value={settings.opacity * 100}
            onChange={e => update({ opacity: Number(e.target.value) / 100 })}
          />
        </label>
      </div>
    </ChartPanel>
  )
}
