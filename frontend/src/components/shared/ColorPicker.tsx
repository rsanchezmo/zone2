import { useState } from 'react'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

const NEON_PRESETS = [
  { hex: '#fc0101', label: 'Red' },
  { hex: '#ff6b00', label: 'Orange' },
  { hex: '#ffd700', label: 'Gold' },
  { hex: '#00ff88', label: 'Green' },
  { hex: '#00aaff', label: 'Blue' },
  { hex: '#7b61ff', label: 'Purple' },
  { hex: '#ff00ff', label: 'Magenta' },
  { hex: '#00ffff', label: 'Cyan' },
  { hex: '#ff1493', label: 'Pink' },
  { hex: '#ffffff', label: 'White' },
]

interface ColorPickerProps {
  value: string
  onChange: (hex: string) => void
}

export default function ColorPicker({ value, onChange }: ColorPickerProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [hexInput, setHexInput] = useState(value)

  function handleHexChange(raw: string) {
    setHexInput(raw)
    const cleaned = raw.startsWith('#') ? raw : `#${raw}`
    if (/^#[0-9a-fA-F]{6}$/.test(cleaned)) {
      onChange(cleaned)
    }
  }

  function handlePresetClick(hex: string) {
    onChange(hex)
    setHexInput(hex)
  }

  function handleNativePickerChange(hex: string) {
    onChange(hex)
    setHexInput(hex)
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 flex-wrap">
        {NEON_PRESETS.map(({ hex, label }) => (
          <button
            key={hex}
            title={label}
            onClick={() => handlePresetClick(hex)}
            className={clsx(
              'w-6 h-6 rounded-full cursor-pointer transition-all duration-150 border-2 shrink-0',
              'hover:scale-110',
              value.toLowerCase() === hex.toLowerCase()
                ? isLight ? 'border-gray-800 scale-110' : 'border-white scale-110'
                : 'border-transparent'
            )}
            style={{
              backgroundColor: hex,
              boxShadow: value.toLowerCase() === hex.toLowerCase()
                ? `0 0 10px ${hex}80`
                : 'none',
            }}
          />
        ))}
      </div>
      <div className="flex items-center gap-2">
        <label
          className={clsx(
            'relative w-7 h-7 rounded-md border cursor-pointer shrink-0 overflow-hidden',
            'transition-shadow duration-150 hover:shadow-md'
          )}
          style={{
            backgroundColor: value,
            borderColor: isLight ? '#e5e5e5' : 'var(--color-surface-500)',
            boxShadow: `0 0 8px ${value}40`,
          }}
          title="Pick any color"
        >
          <input
            type="color"
            value={value}
            onChange={e => handleNativePickerChange(e.target.value)}
            className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
          />
        </label>
        <input
          type="text"
          value={hexInput}
          onChange={e => handleHexChange(e.target.value)}
          placeholder="#fc0101"
          className="input w-28 font-mono text-xs"
          maxLength={7}
        />
      </div>
    </div>
  )
}
