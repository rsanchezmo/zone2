import { useState } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { useRecentPhotos } from '../../api/hooks'
import PhotoLightbox from '../shared/PhotoLightbox'
import { photoThumbUrl } from '../shared/photoUrls'

// Strava-style collage: three large tiles, then a right cluster of one wide +
// two small — the six most recent activity photos.
const COLLAGE_SLOTS = [
  'col-span-2 row-span-2',
  'col-span-2 row-span-2',
  'col-span-2 row-span-2',
  'col-span-2 row-span-1',
  'col-span-1 row-span-1',
  'col-span-1 row-span-1',
]

export default function PhotoCollage() {
  const { data: photos } = useRecentPhotos(6)
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null)
  if (!photos || photos.length === 0) return null

  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Recent photos</span></div>
      <div className="grid grid-cols-8 grid-rows-2 gap-1.5 h-48 sm:h-60 lg:h-72">
        {photos.slice(0, 6).map((photo, idx) => (
          <button
            key={photo.unique_id}
            onClick={() => setLightboxIdx(idx)}
            className={clsx(
              'relative overflow-hidden rounded-lg group ring-1 ring-inset ring-white/10 hover:ring-white/30 transition-all',
              COLLAGE_SLOTS[idx],
            )}
          >
            <img
              src={photoThumbUrl(photo)}
              alt={photo.activity_name || `Photo ${idx + 1}`}
              loading="lazy"
              className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
            <span className="absolute inset-x-0 bottom-0 px-2 py-1 text-[10px] text-white/90 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity truncate">
              {photo.activity_name}
            </span>
          </button>
        ))}
      </div>
      <PhotoLightbox
        photos={photos}
        index={lightboxIdx}
        onIndexChange={setLightboxIdx}
        caption={(_photo, idx) => (
          <Link to={`/activities/${photos[idx].activity_id}`} className="hover:underline">
            {photos[idx].activity_name || 'View activity'}
          </Link>
        )}
      />
    </section>
  )
}
