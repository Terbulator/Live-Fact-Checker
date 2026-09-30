"""Test fixtures for mock claim data.

These are hardcoded test claims used ONLY by unit tests.
They must NEVER be imported by production code.
"""

from typing import Any, Dict, List

MOCK_CLAIMS: List[Dict[str, Any]] = [
    # 1. Numerical / Statistical Claim (Agreed Prompt Example - False)
    {
        "type": "claim",
        "claimId": "claim_001",
        "speaker": "Speaker 1",
        "claim": "The company sold two million units.",
        "timestamp": 12.4,
    },
    # 2. Clearly True Claim
    {
        "type": "claim",
        "claimId": "claim_002",
        "speaker": "Speaker 2",
        "claim": "NASA's Apollo 11 landed humans on the Moon in July 1969.",
        "timestamp": 45.1,
    },
    # 3. Clearly False Claim
    {
        "type": "claim",
        "claimId": "claim_003",
        "speaker": "Speaker 1",
        "claim": "Mount Everest is the highest mountain peak in Africa.",
        "timestamp": 82.0,
    },
    # 4. Unverifiable Claim (No public evidence)
    {
        "type": "claim",
        "claimId": "claim_004",
        "speaker": "Speaker 3",
        "claim": "The CEO privately considers strawberry ice cream his favorite dessert.",
        "timestamp": 115.6,
    },
    # 5. Conflicting / Insufficient Evidence
    {
        "type": "claim",
        "claimId": "claim_005",
        "speaker": "Speaker 2",
        "claim": "The new product release will occur exactly on November 15.",
        "timestamp": 160.2,
    },
    # 6. Additional Statistical Exaggeration Claim (False)
    {
        "type": "claim",
        "claimId": "claim_006",
        "speaker": "Speaker 1",
        "claim": "The national inflation rate dropped by 15% in 2024.",
        "timestamp": 204.8,
    },
]