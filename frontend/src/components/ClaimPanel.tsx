/**
 * The list of claims under check, newest last.
 *
 * A thin wrapper around {@link ClaimCard}: the panel owns the empty state, the
 * heading and the auto-follow behaviour, while each card owns its own verdict
 * presentation.
 */

import { useEffect, useRef } from 'react'

import { ClaimCard } from './ClaimCard'
import type { ClaimCard as ClaimCardModel } from '../types/model'

export interface ClaimPanelProps {
  claims: ClaimCardModel[]
  selectedClaimId: string | null
  onSelect: (claimId: string) => void
}

export function ClaimPanel({ claims, selectedClaimId, onSelect }: ClaimPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null)
  const count = claims.length

  // Follow the newest claim as verdicts land.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [count])

  return (
    <section className="panel panel--claims" aria-label="Claims under check">
      <h2 className="panel__title">
        Claims under check
        {count > 0 && <span className="panel__count">{count}</span>}
      </h2>

      {count === 0 ? (
        <p className="empty">
          Nothing flagged yet. The backend only checks finalized transcript lines,
          so a claim appears the moment a speaker states something verifiable.
        </p>
      ) : (
        <>
          <ul className="cards">
            {claims.map((card) => (
              <ClaimCard
                key={card.claimId}
                card={card}
                selected={card.claimId === selectedClaimId}
                onSelect={onSelect}
              />
            ))}
          </ul>
          <div ref={endRef} />
        </>
      )}
    </section>
  )
}
