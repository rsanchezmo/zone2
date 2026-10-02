import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import type { ActivityDetail, ActivityPhoto as StravaPhoto } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import { parseLocalDate } from '../../utils/dates'
import ExportButton from '../shared/ExportButton'
import ResyncActivityButton from '../shared/ResyncActivityButton'
import PhotoLightbox from '../shared/PhotoLightbox'
import { photoThumbUrl } from '../shared/photoUrls'
import {
  DeviceIcon, ShoeIcon, ThermometerIcon, ClockIcon, DumbbellIcon, MedalIcon, TrophyIcon,
} from '../icons'

function PhotoGallery({ photos }: { photos: StravaPhoto[] }) {
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null)

  return (
    <>
      {/* Compact horizontal thumbnail strip */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
        {photos.map((photo, idx) => (
          <button
            key={photo.unique_id}
            onClick={() => setLightboxIdx(idx)}
            className="relative flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden group cursor-pointer ring-1 ring-inset ring-white/10 hover:ring-white/30 transition-all"
          >
            <img
              src={photoThumbUrl(photo)}
              alt={photo.caption || `Photo ${idx + 1}`}
              className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-110"
              loading="lazy"
            />
          </button>
        ))}
      </div>

      <PhotoLightbox photos={photos} index={lightboxIdx} onIndexChange={setLightboxIdx} />
    </>
  )
}

/** Back link, sport, name and actions, then the description, photos and metadata pills. */
export default function ActivityHeader({ activity, id }: { activity: ActivityDetail; id: string | undefined }) {
  const navigate = useNavigate()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const sportAccent = getSportColor(activity.sport_type)

  return (
    <header>
      <button
        onClick={() => navigate(-1)}
        className={clsx(
          'action-link group gap-1.5 text-[11px] uppercase tracking-[0.18em] mb-4 transition-colors duration-150',
          isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-500 hover:text-gray-100',
        )}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 16 16"
          fill="currentColor"
          className="w-3 h-3 transition-transform duration-150 group-hover:-translate-x-0.5"
          aria-hidden="true"
        >
          <path fillRule="evenodd" d="M9.78 4.22a.75.75 0 0 1 0 1.06L7.06 8l2.72 2.72a.75.75 0 1 1-1.06 1.06L5.47 8.53a.75.75 0 0 1 0-1.06l3.25-3.25a.75.75 0 0 1 1.06 0Z" clipRule="evenodd" />
        </svg>
        Back
      </button>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3 flex-wrap mb-2">
            <span
              className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] font-semibold px-2 py-1 rounded-full border"
              style={{
                backgroundColor: `${sportAccent}15`,
                color: sportAccent,
                borderColor: `${sportAccent}40`,
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: sportAccent }} aria-hidden="true" />
              {activity.sport_type}
            </span>
            <span className={clsx('text-[11px] font-mono tabular-nums', isLight ? 'text-gray-500' : 'text-gray-500')}>
              {activity.start_date_local ? parseLocalDate(activity.start_date_local).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' }) : ''}
            </span>
          </div>
          <h2
            className={clsx('text-2xl md:text-3xl font-semibold tracking-tight leading-tight', isLight ? 'text-gray-900' : 'text-gray-100')}
            style={{ letterSpacing: '-0.02em' }}
          >
            {activity.name}
          </h2>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <ResyncActivityButton activityId={id ?? ''} />
          <ExportButton
            url={`/api/exports/activity/${id}`}
            label="PNG"
            filename={`activity_${id}.png`}
            exportType="activity"
          />
        </div>
      </div>

      {activity.description && (
        <p className={clsx('text-sm mt-4 whitespace-pre-line max-w-3xl', isLight ? 'text-gray-600' : 'text-gray-400')}>
          {activity.description}
        </p>
      )}
      {activity.photos && activity.photos.length > 0 && (
        <div className="mt-5">
          <PhotoGallery photos={activity.photos} />
        </div>
      )}

      {/* Metadata pills — hairline-bordered, sport-agnostic */}
      {(activity.device_name || activity.gear || activity.average_temp != null || activity.timezone || activity.workout_type != null || (activity.pr_count ?? 0) > 0 || (activity.achievement_count ?? 0) > 0) && (
        <div className="flex flex-wrap gap-1.5 mt-5">
          {activity.device_name && <MetaPill icon={<DeviceIcon size={11} />} text={activity.device_name} />}
          {activity.gear && (
            <MetaPill
              icon={<ShoeIcon size={11} />}
              text={activity.gear.nickname || activity.gear.name}
              suffix={activity.gear.converted_distance != null ? `${Math.round(activity.gear.converted_distance)} km` : undefined}
            />
          )}
          {activity.average_temp != null && <MetaPill icon={<ThermometerIcon size={11} />} text={`${Math.round(activity.average_temp)}°C`} />}
          {activity.timezone && <MetaPill icon={<ClockIcon size={11} />} text={activity.timezone.replace(/^\(.*?\)\s*/, '')} />}
          {activity.workout_type != null && <MetaPill icon={<DumbbellIcon size={11} />} text={String(activity.workout_type)} />}
          {(activity.pr_count ?? 0) > 0 && (
            <MetaPill icon={<MedalIcon size={11} />} text={`${activity.pr_count} PR${(activity.pr_count ?? 0) > 1 ? 's' : ''}`} tone="amber" />
          )}
          {(activity.achievement_count ?? 0) > 0 && (
            <MetaPill icon={<TrophyIcon size={11} />} text={`${activity.achievement_count} achievement${(activity.achievement_count ?? 0) > 1 ? 's' : ''}`} tone="green" />
          )}
        </div>
      )}
    </header>
  )
}

// ────────────────────────────────────────────────────────
// MetaPill — compact header-level metadata chip
// ────────────────────────────────────────────────────────

function MetaPill({
  icon,
  text,
  suffix,
  tone = 'neutral',
}: {
  icon: ReactNode
  text: string
  suffix?: string
  tone?: 'neutral' | 'amber' | 'green'
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const palette =
    tone === 'amber'
      ? (isLight ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-amber-500/10 text-amber-400 border-amber-500/30')
      : tone === 'green'
        ? (isLight ? 'bg-green-50 text-green-700 border-green-200' : 'bg-green-500/10 text-green-400 border-green-500/30')
        : (isLight ? 'bg-gray-50 text-gray-600 border-gray-200' : 'bg-surface-700/60 text-gray-400 border-surface-600')
  return (
    <span className={clsx(
      'inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border font-medium',
      palette,
    )}>
      <span className="opacity-70 shrink-0" aria-hidden="true">{icon}</span>
      <span>{text}</span>
      {suffix && <span className="opacity-50 tabular-nums">· {suffix}</span>}
    </span>
  )
}
