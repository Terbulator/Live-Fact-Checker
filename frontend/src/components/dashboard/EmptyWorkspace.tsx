/**
 * The empty conversation.
 *
 * The promise, once, above the composer. No sample claims, no example verdicts,
 * no score, no suggested transcript: a first-time reader has to be able to tell
 * that nothing here has been checked yet, and invented content would be the one
 * thing on this page that could not be trusted.
 */

export function EmptyWorkspace() {
  return (
    <section className="welcome" aria-label="Start a fact-check">
      <h2 className="welcome__title">Fact-check anything.</h2>
      <p className="welcome__lede">
        Send a claim, video, URL, audio, or start listening.
      </p>
      <ul className="welcome__list">
        <li>
          <span className="welcome__key">Enter</span>
          claims are checked against live sources
        </li>
        <li>
          <span className="welcome__key">Paste a link</span>
          a YouTube video or a direct video file
        </li>
        <li>
          <span className="welcome__key">Voice</span>
          claims are checked as they are spoken
        </li>
      </ul>
    </section>
  )
}
