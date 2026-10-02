/**
 * Media submission rules.
 *
 * One place decides what counts as a video, an audio file and an analysable
 * link, because three surfaces need to agree: the composer (which recognises
 * what has been typed or picked), the ingestion path (which validates before
 * uploading), and the message bubble (which labels the attachment).
 *
 * Keeping the rules here rather than inside a component is what stops the
 * composer and the ingestion endpoint from disagreeing -- a link the composer
 * offers to analyse must be one the endpoint accepts.
 */

export type MediaKind = 'audio' | 'video' | 'url'

/** Accepted audio containers, by MIME type then by extension. */
const AUDIO_TYPES = [
  'audio/mpeg',
  'audio/mp3',
  'audio/wav',
  'audio/x-wav',
  'audio/mp4',
  'audio/m4a',
  'audio/x-m4a',
  'audio/ogg',
  'audio/webm',
  'audio/flac',
]
const AUDIO_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.webm', '.flac']

/** Accepted video containers. */
const VIDEO_TYPES = [
  'video/mp4',
  'video/quicktime',
  'video/x-msvideo',
  'video/x-matroska',
  'video/webm',
  'video/x-webm',
]
const VIDEO_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.webm']

/** The backend's ceiling, mirrored so a file is refused before the upload. */
export const MAX_AUDIO_BYTES = 100 * 1024 * 1024
export const MAX_VIDEO_BYTES = 500 * 1024 * 1024

export const AUDIO_SUPPORT =
  'Supported: MP3, WAV, M4A, OGG, WebM, FLAC'
export const VIDEO_SUPPORT =
  'Supported: MP4, MOV, AVI, MKV, WebM'
export const URL_SUPPORT =
  'Supported: YouTube videos and direct video links (.mp4, .webm, .mov, .mkv, .avi)'

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot).toLowerCase()
}

/** Which kind of media a picked file is, or null when it is neither. */
export function fileKind(file: File): Exclude<MediaKind, 'url'> | null {
  const extension = extensionOf(file.name)
  if (AUDIO_TYPES.includes(file.type) || AUDIO_EXTENSIONS.includes(extension)) return 'audio'
  if (VIDEO_TYPES.includes(file.type) || VIDEO_EXTENSIONS.includes(extension)) return 'video'
  return null
}

/**
 * Whether a file may be submitted.
 *
 * Returns the reason rather than a boolean so the caller can show the reader
 * which limit was hit, which is more useful than a generic rejection.
 */
export function validateFile(file: File, kind: Exclude<MediaKind, 'url'>): string | null {
  if (fileKind(file) !== kind) {
    return kind === 'audio'
      ? `Unsupported audio format. ${AUDIO_SUPPORT}`
      : `Unsupported video format. ${VIDEO_SUPPORT}`
  }
  const ceiling = kind === 'audio' ? MAX_AUDIO_BYTES : MAX_VIDEO_BYTES
  if (file.size > ceiling) {
    return kind === 'audio'
      ? 'File too large. Maximum: 100MB'
      : 'File too large. Maximum: 500MB'
  }
  return null
}

/** The whole trimmed string is a single http(s) URL. */
export function isBareUrl(text: string): boolean {
  const trimmed = text.trim()
  if (trimmed === '' || /\s/.test(trimmed)) return false
  try {
    const url = new URL(trimmed)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

const YOUTUBE = /^https?:\/\/(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/|live\/)|youtu\.be\/)[\w-]+/
const DIRECT_VIDEO = /\.(mp4|webm|mov|mkv|avi)($|\?)/i

/** Whether the ingestion endpoint can process this link. */
export function isAnalysableUrl(url: string): boolean {
  return YOUTUBE.test(url) || DIRECT_VIDEO.test(url)
}

/** Why a link cannot be analysed, or null when it can. */
export function validateUrl(url: string): string | null {
  const trimmed = url.trim()
  if (trimmed === '') return 'Please enter a URL'
  try {
    new URL(trimmed)
  } catch {
    return 'Invalid URL format'
  }
  if (!isAnalysableUrl(trimmed)) return `Unsupported URL. ${URL_SUPPORT}`
  return null
}

/**
 * A short name for a link, for the attachment preview.
 *
 * A YouTube link becomes "YouTube video"; anything else becomes its host, so
 * the reader recognises the source without the full query string.
 */
export function urlLabel(url: string): string {
  if (YOUTUBE.test(url)) return 'YouTube video'
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** A readable file size, for the attachment preview. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const megabytes = bytes / (1024 * 1024)
  if (megabytes >= 1) return `${megabytes.toFixed(megabytes >= 10 ? 0 : 1)} MB`
  return `${Math.round(bytes / 1024)} KB`
}
