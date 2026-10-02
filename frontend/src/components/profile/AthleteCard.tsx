import clsx from 'clsx'
import type { AthleteProfile } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'

export default function AthleteCard({ profile }: { profile: AthleteProfile }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const fullName = `${profile.firstname ?? ''} ${profile.lastname ?? ''}`.trim()
  const location = [profile.city, profile.state, profile.country].filter(Boolean).join(', ')

  return (
    <section
      className={clsx(
        'panel hero-brackets p-6 md:p-8 flex items-center gap-6',
        isLight ? 'bg-white' : 'bg-surface-800',
      )}
      style={{ ['--card-accent' as string]: (profile.premium || profile.summit) ? '#eab308' : '#6b7280' }}
    >
      {profile.profile_medium && profile.profile_medium !== 'avatar/athlete/large.png' ? (
        <img
          src={profile.profile_medium}
          alt={fullName}
          className={clsx('w-24 h-24 rounded-full border object-cover shrink-0', isLight ? 'border-gray-200' : 'border-surface-600')}
        />
      ) : (
        <div className={clsx(
          'w-24 h-24 rounded-full border flex items-center justify-center text-3xl font-semibold shrink-0',
          isLight ? 'border-gray-200 bg-gray-100 text-gray-400' : 'border-surface-600 bg-surface-700 text-gray-500',
        )}>
          {(profile.firstname?.[0] ?? '?').toUpperCase()}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="eyebrow mb-1.5">Athlete</div>
        <h1
          className={clsx('text-2xl md:text-3xl font-semibold tracking-tight truncate', isLight ? 'text-gray-900' : 'text-gray-100')}
          style={{ letterSpacing: '-0.02em' }}
        >
          {fullName || 'Athlete'}
        </h1>
        <div className="flex items-center gap-3 mt-1.5 flex-wrap text-[11px] font-mono tabular-nums">
          {profile.username && (
            <span className={isLight ? 'text-gray-500' : 'text-gray-500'}>@{profile.username}</span>
          )}
          {location && (
            <>
              {profile.username && <span className={isLight ? 'text-gray-300' : 'text-gray-700'}>·</span>}
              <span className={isLight ? 'text-gray-500' : 'text-gray-500'}>{location}</span>
            </>
          )}
          {(profile.premium || profile.summit) && (
            <>
              <span className={isLight ? 'text-gray-300' : 'text-gray-700'}>·</span>
              <span className="uppercase tracking-[0.15em] text-amber-400 text-[10px] font-semibold">Subscriber</span>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
