import { useState } from 'react'
import type { RaceEvent, RaceEventInput } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import {
  formatPace, fromInputDist, getDistUnit, getPaceUnit, isSpeedSport, parsePaceInput, toInputDist,
} from '../../utils/formatSpeed'
import DatePicker from './DatePicker'
import SportTypeCombobox from './SportTypeCombobox'

interface RaceEventFormProps {
  /** The race being edited, or null for a new one. */
  initial: RaceEvent | null
  /** Date a new race starts with. */
  date?: string
  /** False when the form is opened on a day, which is then the race's date. */
  dateField?: boolean
  accent: string
  onSubmit: (race: RaceEventInput) => void
  onCancel: () => void
}

/** Race event fields with Save / Cancel. Remount it (key) to start from another race. */
export default function RaceEventForm({ initial, date: newDate, dateField = true, accent, onSubmit, onCancel }: RaceEventFormProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [name, setName] = useState(initial?.name ?? '')
  const [date, setDate] = useState(initial?.date ?? newDate ?? '')
  const [sportType, setSportType] = useState(initial?.sport_type ?? 'Run')
  const [distance, setDistance] = useState(initial?.distance_km != null ? toInputDist(initial.distance_km, initial.sport_type) : '')
  const [targetPace, setTargetPace] = useState(
    initial?.target_pace != null ? formatPace(initial.target_pace, isSpeedSport(initial.sport_type)) : '',
  )
  const [location, setLocation] = useState(initial?.location ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')

  const paceUnit = getPaceUnit(sportType)
  const canSubmit = !!name.trim() && !!date

  const submit = () => {
    if (!canSubmit) return
    onSubmit({
      name: name.trim(),
      date,
      sport_type: sportType,
      distance_km: fromInputDist(distance, sportType),
      target_pace: targetPace ? parsePaceInput(targetPace, isSpeedSport(sportType)) : null,
      description: description || null,
      location: location || null,
      url: url || null,
    })
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2">
          <label className="eyebrow mb-1.5 block">Race name *</label>
          <input
            type="text" placeholder="e.g. Berlin Marathon"
            value={name} onChange={e => setName(e.target.value)}
            className="input w-full"
            autoFocus
          />
        </div>
        {dateField && (
          <div>
            <label className="eyebrow mb-1.5 block">Date *</label>
            <DatePicker value={date} onChange={setDate} inputClassName="w-full" />
          </div>
        )}
        <div>
          <label className="eyebrow mb-1.5 block">Sport</label>
          <SportTypeCombobox value={sportType} onChange={setSportType} className="input w-full" isLight={isLight} />
        </div>
        <div>
          <label className="eyebrow mb-1.5 block">Distance ({getDistUnit(sportType)})</label>
          <input
            type="text" inputMode="decimal"
            placeholder={getDistUnit(sportType) === 'm' ? '1500' : '42.195'}
            value={distance} onChange={e => setDistance(e.target.value)}
            className="input w-full"
          />
        </div>
        <div>
          <label className="eyebrow mb-1.5 block">Target pace ({paceUnit})</label>
          <input
            type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:00' : '30'}
            value={targetPace} onChange={e => setTargetPace(e.target.value)}
            className="input w-full"
          />
        </div>
        <div>
          <label className="eyebrow mb-1.5 block">Location</label>
          <input
            type="text" placeholder="Berlin, Germany"
            value={location} onChange={e => setLocation(e.target.value)}
            className="input w-full"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="eyebrow mb-1.5 block">URL</label>
          <input
            type="text" placeholder="https://…"
            value={url} onChange={e => setUrl(e.target.value)}
            className="input w-full"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="eyebrow mb-1.5 block">Notes</label>
          <textarea
            placeholder="Goals, strategy, notes…"
            value={description} onChange={e => setDescription(e.target.value)}
            className="input w-full"
            rows={3}
          />
        </div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={submit}
          disabled={!canSubmit}
          className="btn flex-1 !text-sm !py-2"
          style={{ borderColor: `${accent}50`, color: accent, backgroundColor: `${accent}15` }}
        >
          {initial ? 'Save changes' : 'Add race'}
        </button>
        <button onClick={onCancel} className="btn !text-sm !py-2 px-6">Cancel</button>
      </div>
    </div>
  )
}
