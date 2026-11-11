import clsx from 'clsx'
import type { AthleteProfile } from '../../api/athlete'

export default function AthleteDetails({ profile, totalActivities }: { profile: AthleteProfile; totalActivities: number | undefined }) {
  const createdAt = profile.created_at ? new Date(profile.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null
  const updatedAt = profile.updated_at ? new Date(profile.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null

  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Details</span></div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {profile.sex && <InfoTile label="Gender" value={profile.sex === 'M' ? 'Male' : profile.sex === 'F' ? 'Female' : profile.sex} />}
        {profile.weight != null && profile.weight > 0 && <InfoTile label="Weight" value={profile.weight} unit="kg" />}
        {totalActivities != null && <InfoTile label="Activities" value={totalActivities.toLocaleString()} />}
        {profile.ftp != null && profile.ftp > 0 && <InfoTile label="FTP" value={profile.ftp} unit="W" />}
        {profile.follower_count != null && <InfoTile label="Followers" value={profile.follower_count.toLocaleString()} />}
        {profile.friend_count != null && <InfoTile label="Following" value={profile.friend_count.toLocaleString()} />}
        {createdAt && <InfoTile label="Member since" value={createdAt} compact />}
        {updatedAt && <InfoTile label="Last updated" value={updatedAt} compact />}
      </div>
    </section>
  )
}

// ────────────────────────────────────────────────────────
// InfoTile — a clean detail tile for the athlete info strip
// ────────────────────────────────────────────────────────

export function InfoTile({ label, value, unit, compact }: { label: string; value: string | number; unit?: string; compact?: boolean }) {
  return (
    <div className={clsx(
      'panel p-4',
      )}>
      <div className="eyebrow mb-1.5">{label}</div>
      <div className={clsx(
        'font-mono tabular-nums font-semibold tracking-tight',
        compact ? 'text-sm' : 'text-xl',
        'text-fg-strong',
      )}>
        {value}
        {unit && <span className={clsx('ml-1 font-medium tracking-normal', compact ? 'text-[11px]' : 'text-xs', 'text-fg-subtle')}>{unit}</span>}
      </div>
    </div>
  )
}
