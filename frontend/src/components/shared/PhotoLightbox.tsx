import { useCallback, useEffect, type ReactNode } from 'react'
import clsx from 'clsx'
import { photoFullUrl, photoThumbUrl, type LightboxPhoto } from './photoUrls'

/** Fullscreen photo viewer with keyboard nav and a thumbnail strip. Controlled
 *  by `index` (null = closed). `caption` overrides the per-photo caption line,
 *  e.g. to show a link back to the source activity. */
export default function PhotoLightbox({
  photos,
  index,
  onIndexChange,
  caption,
}: {
  photos: LightboxPhoto[]
  index: number | null
  onIndexChange: (i: number | null) => void
  caption?: (photo: LightboxPhoto, index: number) => ReactNode
}) {
  const close = useCallback(() => onIndexChange(null), [onIndexChange])
  const prev = useCallback(
    () => onIndexChange(index !== null ? (index - 1 + photos.length) % photos.length : null),
    [index, photos.length, onIndexChange],
  )
  const next = useCallback(
    () => onIndexChange(index !== null ? (index + 1) % photos.length : null),
    [index, photos.length, onIndexChange],
  )

  useEffect(() => {
    if (index === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, close, prev, next])

  if (index === null) return null
  const current = photos[index]
  const capNode = caption ? caption(current, index) : current.caption

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/90 backdrop-blur-sm"
      onClick={close}
    >
      <button
        onClick={(e) => { e.stopPropagation(); close() }}
        className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white text-xl transition-colors"
      >
        &times;
      </button>
      {photos.length > 1 && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); prev() }}
            className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white text-lg transition-colors"
          >
            &#8249;
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); next() }}
            className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white text-lg transition-colors"
          >
            &#8250;
          </button>
        </>
      )}
      <img
        src={photoFullUrl(current)}
        alt={current.caption || ''}
        className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
      {capNode && (
        <div
          className="absolute bottom-16 left-1/2 -translate-x-1/2 text-white/80 text-sm bg-black/50 px-4 py-2 rounded-lg"
          onClick={(e) => e.stopPropagation()}
        >
          {capNode}
        </div>
      )}
      {photos.length > 1 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-1.5">
          {photos.map((photo, idx) => (
            <button
              key={photo.unique_id}
              onClick={(e) => { e.stopPropagation(); onIndexChange(idx) }}
              className={clsx(
                'w-10 h-10 rounded overflow-hidden transition-all flex-shrink-0',
                idx === index ? 'ring-2 ring-white opacity-100' : 'opacity-50 hover:opacity-80',
              )}
            >
              <img src={photoThumbUrl(photo)} alt="" className="w-full h-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
