import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useAgentSettings, useAgentUsage, useSetAgentSettings, type AgentUsage as Usage } from '../../api/agent'
import { useTheme } from '../../hooks/useTheme'
import { dateToLocalStr, parseLocalDate, todayLocalStr } from '../../utils/dates'
import ChartPanel from '../shared/ChartPanel'
import { ACCENT, fmtDate, useGarminChartProps } from '../garmin/garmin'
import { InfoTile } from './AthleteDetails'

const DAYS = 30
// cyan-600: the brand cyan keeps 3:1 contrast on the light surface
const ACCENT_ON_LIGHT = '#0891b2'
const OPENAI_BILLING = 'https://platform.openai.com/settings/organization/billing/overview'
const compact = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })

function usd(value: number): string {
  return `$${value.toFixed(value >= 1 || value === 0 ? 2 : 3)}`
}

function price(value: number | null): string {
  return value == null ? '?' : `$${value < 1 ? value.toFixed(2) : value.toFixed(value % 1 ? 2 : 0)}`
}

/** The coach on the Profile page: its model, the credit left, and what it cost. */
export default function AgentUsage() {
  const { data } = useAgentUsage(DAYS)
  return (
    <section className="space-y-3">
      <div className="section-head mb-4">
        <span className="eyebrow">Coach</span>
        {data && <span className="text-[11px] font-mono text-gray-500">{data.model}</span>}
      </div>
      <CoachSettings credit={data?.credit ?? null} />
      {data && <Spend data={data} />}
    </section>
  )
}

function CoachSettings({ credit }: { credit: Usage['credit'] }) {
  const { data: settings } = useAgentSettings()
  const save = useSetAgentSettings()
  const [topUp, setTopUp] = useState('')
  if (!settings) return null
  const row = 'flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3'
  const amount = Number(topUp)

  return (
    <div className="rounded-lg border divide-y bg-surface-800 border-surface-600 divide-surface-600">
      <div className={row}>
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">Model</div>
          <p className="text-[11px] text-gray-500">Price per million tokens, in and out. Cheaper models answer simple questions just as well.</p>
        </div>
        <select
          className="select"
          aria-label="Coach model"
          value={settings.model}
          onChange={e => save.mutate({ model: e.target.value })}
          disabled={save.isPending}
        >
          {settings.models.map(m => (
            <option key={m.id} value={m.id}>{m.name} · {price(m.input_usd)} / {price(m.output_usd)}</option>
          ))}
          {!settings.models.some(m => m.id === settings.model) && <option value={settings.model}>{settings.model}</option>}
        </select>
      </div>

      <div className={row}>
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">
            Credit left
            {credit && (
              <span className={clsx('ml-2 font-mono tabular-nums font-semibold', credit.left_usd < 1 ? 'text-red-400' : 'text-fg-strong')}>
                ≈ {usd(Math.max(0, credit.left_usd))}
              </span>
            )}
          </div>
          <p className="text-[11px] text-gray-500">
            {credit
              ? `Of ${usd(credit.added_usd)} topped up on ${fmtDate(credit.since)}, less what z2 has counted since. `
              : 'OpenAI has no way to read your balance, so enter what you top up and z2 counts down. '}
            <a href={OPENAI_BILLING} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-gray-300">Exact balance on OpenAI</a>
          </p>
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={e => {
            e.preventDefault()
            if (amount > 0) save.mutate({ credit_usd: amount }, { onSuccess: () => setTopUp('') })
          }}
        >
          <span className="text-[12px] text-gray-500">$</span>
          <input
            type="number"
            min="0"
            step="1"
            inputMode="decimal"
            value={topUp}
            onChange={e => setTopUp(e.target.value)}
            placeholder={credit ? credit.added_usd.toString() : '10'}
            aria-label="Credit topped up, in dollars"
            className="w-20 rounded-md px-2 py-1 text-[13px] font-mono outline-none bg-surface-700"
          />
          <button type="submit" disabled={!(amount > 0) || save.isPending} className="text-[12px] font-medium text-blue-500 disabled:text-gray-500">
            {credit ? 'New top-up' : 'Save'}
          </button>
        </form>
      </div>
    </div>
  )
}

function Spend({ data }: { data: Usage }) {
  const { theme, colors } = useTheme()
  const { chartMargin, xAxisProps, yAxisProps, tooltipProps } = useGarminChartProps()

  // Every day of the window, so quiet days show as gaps on a continuous axis
  const days = useMemo(() => {
    const byDate = new Map(data.days.map(d => [d.date, d]))
    const start = parseLocalDate(todayLocalStr())
    start.setDate(start.getDate() - (DAYS - 1))
    return Array.from({ length: DAYS }, (_, i) => {
      const day = new Date(start)
      day.setDate(start.getDate() + i)
      const date = dateToLocalStr(day)
      return byDate.get(date) ?? { date, runs: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 }
    })
  }, [data])

  const { all_time: total, this_month: month } = data
  if (total.runs === 0) {
    return <p className="text-[11px] text-gray-500">No conversations with the coach yet. What they cost shows up here.</p>
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <InfoTile label="This month" value={usd(month.cost_usd)} />
        <InfoTile label="All time" value={usd(total.cost_usd)} />
        <InfoTile label="Turns" value={total.runs.toLocaleString()} />
        <InfoTile label="Tokens in / out" value={`${compact.format(total.input_tokens)} / ${compact.format(total.output_tokens)}`} />
      </div>
      <ChartPanel
        title={`Spend per day · last ${DAYS} days`}
        glow={false}
        footer={
          <span className="text-[11px] text-gray-500">
            {total.requests.toLocaleString()} model requests and {total.tool_calls.toLocaleString()} tool calls
            over {total.runs.toLocaleString()} turns; {compact.format(total.cache_read_tokens)} input tokens read
            from cache. Speech is an estimate from the characters read aloud.
            {total.unpriced_runs > 0 && ` ${total.unpriced_runs} turns ran on a model without a known price and aren't in the totals.`}
          </span>
        }
      >
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={days} margin={chartMargin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxisProps} />
            <YAxis {...yAxisProps} tickFormatter={(v: number) => usd(v)} />
            <Tooltip
              {...tooltipProps}
              formatter={(_value: unknown, _name: unknown, item: { payload?: (typeof days)[number] }) => {
                const d = item.payload
                if (!d) return ['', '']
                return [`${usd(d.cost_usd)} · ${d.runs} ${d.runs === 1 ? 'turn' : 'turns'} · ${compact.format(d.input_tokens)} in / ${compact.format(d.output_tokens)} out`, 'Spent']
              }}
            />
            <Bar dataKey="cost_usd" fill={theme === 'light' ? ACCENT_ON_LIGHT : ACCENT} radius={[4, 4, 0, 0]} maxBarSize={14} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </ChartPanel>
    </div>
  )
}
