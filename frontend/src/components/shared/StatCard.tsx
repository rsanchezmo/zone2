import clsx from 'clsx'

interface StatCardProps {
  label: string
  value: string | number
  unit?: string
  delta?: number | string | null
  sublabel?: string
  color?: string
}

export default function StatCard({ label, value, unit, delta, sublabel, color = 'text-neon-red' }: StatCardProps) {
  return (
    <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={clsx('text-2xl font-bold', color)}>
        {value}
        {unit && <span className="text-sm text-gray-400 ml-1">{unit}</span>}
      </div>
      {delta !== undefined && delta !== null && (
        <div className={clsx('text-xs mt-1',
          delta === 'new' ? 'text-green-400' : (delta as number) >= 0 ? 'text-green-400' : 'text-red-400'
        )}>
          {delta === 'new' ? <span className="inline-block w-2 h-2 rounded-full bg-green-400" /> : `${(delta as number) >= 0 ? '+' : ''}${(delta as number).toFixed(1)}%`}
        </div>
      )}
      {sublabel && <div className="text-[11px] text-gray-500 mt-1">{sublabel}</div>}
    </div>
  )
}
