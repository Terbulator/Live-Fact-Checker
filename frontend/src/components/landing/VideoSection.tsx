import { Play } from 'lucide-react'
import { motion } from 'framer-motion'

import { SectionSurface, surfaceClass } from './tone'

/**
 * Reusable cinematic video slot for the marketing site.
 *
 * Four sections use this: the hero product demo, the pipeline demo, the
 * verification demo and the video-analysis demo. Each passes its own
 * `videoSrc`; while a source is empty the component renders a designed
 * placeholder rather than an error or a broken player.
 *
 * To publish a real recording, drop the file in `frontend/public/videos/` and
 * pass its path. Nothing else needs to change.
 */
export interface VideoSectionProps {
  /** Small uppercase label above the title. */
  eyebrow?: string
  /** Section heading. */
  title: string
  /** Supporting copy under the heading. */
  description?: string
  /**
   * Path or URL to the recording. Leave empty for the placeholder state.
   * Local files belong in `frontend/public/videos/`, e.g. "/videos/hero-demo.mp4".
   */
  videoSrc?: string
  /** Poster frame shown before playback. Same directory rules as `videoSrc`. */
  poster?: string
  /** Extra class on the wrapping `<section>`. */
  className?: string
  /** Identifier for deep links and scroll targets. */
  id?: string
  /** Label shown in the placeholder state. */
  placeholderLabel?: string
  /** Ground treatment for the surrounding section. The frame stays dark. */
  surface?: SectionSurface
}

/** Aspect ratio keeps every slot 16:9, which is also the responsive default. */
export function VideoSection({
  eyebrow,
  title,
  description,
  videoSrc,
  poster,
  className,
  id,
  placeholderLabel = 'Product demonstration',
  surface = 'white',
}: VideoSectionProps) {
  const hasVideo = typeof videoSrc === 'string' && videoSrc.trim().length > 0

  return (
    <section
      id={id}
      className={`lfp-section lfp-video ${surfaceClass(surface)}${className ? ` ${className}` : ''}`}
    >
      <div className="lfp-container">
        {eyebrow ? <span className="lfp-eyebrow">{eyebrow}</span> : null}
        <h2 className="lfp-h2 lfp-h2--center">{title}</h2>
        {description ? <p className="lfp-lede lfp-lede--center">{description}</p> : null}

        <motion.figure
          className="lfp-video__frame"
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-120px' }}
          transition={{ duration: 0.6, ease: [0.2, 0.7, 0.3, 1] }}
        >
          {hasVideo ? (
            <video
              className="lfp-video__media"
              src={videoSrc}
              poster={poster}
              controls
              playsInline
              preload="metadata"
              aria-label={title}
            />
          ) : (
            /*
             * Placeholder state. Deliberately not a <video> element: an empty
             * source would render a native error box, which reads as a broken
             * page rather than an unwatched demo slot.
             */
            <div className="lfp-video__placeholder" role="img" aria-label={`${placeholderLabel} — video coming soon`}>
              <span className="lfp-video__scan" aria-hidden="true" />
              <span className="lfp-video__glyph" aria-hidden="true">
                <Play size={26} strokeWidth={1.6} fill="currentColor" />
              </span>
              <span className="lfp-video__label">{placeholderLabel}</span>
              <span className="lfp-video__hint">MP4 or WebM · fullscreen · captions</span>
            </div>
          )}
        </motion.figure>

        {/* The one accent allowed in a video band. */}
        <p className="lfp-video__badge">
          <span className="lfp-video__badgeDot" aria-hidden="true" />
          {hasVideo ? 'Demo recording' : 'Recording in progress'}
        </p>
      </div>
    </section>
  )
}
