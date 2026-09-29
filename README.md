# Live Fact-Checker

Two modules currently live in this repository:

* **Backend** (`backend/`) — HTTP API, WebSocket event layer, session
  management, event validation and routing. Documented below.
* **Verification module** (`verification/`) — the standalone verification
  pipeline, documented in the second half of this file.

---

# Part 1 — Backend

The backend is the hub of the Live Fact-Checker pipeline. It owns the HTTP API,
the WebSocket server, sessions, validation, routing, structured logging, CORS
and a fully offline mock pipeline.

```text
Audio
  ↓
AssemblyAI Realtime STT            (Tushar)
  ↓  TranscriptEvent
BACKEND
  ↓  ClaimEvent
Claim Intelligence                 (Atif)
  ↓  VerificationEvent
Verification / Evidence            (Nayanika)
  ↓
BACKEND WebSocket
  ↓
Frontend                           (Rupan)
```

The backend does **not** implement AssemblyAI streaming, claim extraction or
evidence reasoning. It routes validated events between those modules and the
frontend.

## Requirements

* Python 3.10+ (developed and tested on 3.14)

## Setup

```bash
# Create and activate the virtual environment
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

All configuration comes from environment variables. Copy the example file and
fill in what you need:

```bash
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

`.env` is git-ignored. Never commit real credentials. Secrets are read
server-side only and are never sent to the browser; `GET /health` reports only
whether a key is **present**, never its value.

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` / `production` / `test` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Server bind address |
| `CORS_ORIGINS` | local dev origins | Comma-separated allowed browser origins |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `LOG_JSON` | `false` | Emit machine-readable JSON logs |
| `USE_MOCK_ENGINES` | `true` | Use the offline mock claim/verification engines |
| `ASSEMBLYAI_API_KEY` | *(empty)* | AssemblyAI realtime STT (Tushar) |
| `LLM_GATEWAY_API_KEY` | *(empty)* | Claim extraction via LLM gateway (Atif) |
| `SEARCH_API_KEY` | *(empty)* | Evidence retrieval / web search (Nayanika) |

A wildcard `*` in `CORS_ORIGINS` is rejected when `ENVIRONMENT=production`.

## Running the backend

```bash
# Development (auto-reload)
uvicorn backend.main:app --reload

# Explicit host and port
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Interactive API docs: <http://127.0.0.1:8000/docs>

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health, wired engines, credential presence |
| `POST` | `/session/start` | Create a session (backend owns `sessionId`) |
| `POST` | `/session/stop?sessionId=...` | Stop a session and close its clients |
| `GET` | `/session/{session_id}` | Session state and event counters |
| `POST` | `/events/transcript` | Ingest a transcript; runs the full pipeline |
| `POST` | `/events/claim` | Ingest a claim; runs verification |
| `POST` | `/events/verification` | Ingest an externally produced verification |
| `WS` | `/ws/session/{session_id}` | Realtime event stream |

### Create a session

```bash
curl -X POST http://127.0.0.1:8000/session/start \
  -H "Content-Type: application/json" -d '{}'
```

```json
{
  "sessionId": "session_001",
  "status": "started",
  "createdAt": "2026-09-28T10:14:53.175511+00:00",
  "updatedAt": "2026-09-28T10:14:53.175533+00:00",
  "connectedClients": 0,
  "transcriptCount": 0,
  "claimCount": 0,
  "verificationCount": 0,
  "errorCount": 0,
  "wsUrl": "ws://127.0.0.1:8000/ws/session/session_001",
  "type": "session"
}
```

Pass `{"startMockPipeline": true}` to immediately replay the offline demo
stream into the new session.

### Ingest a transcript

```bash
curl -X POST http://127.0.0.1:8000/events/transcript \
  -H "Content-Type: application/json" \
  -d '{"type":"transcript","sessionId":"session_001","speaker":"Speaker 1",
       "text":"India won the 2011 Cricket World Cup.","timestamp":12.4,
       "isFinal":true}'
```

Returns `202 Accepted` with the claim and verification that were produced, and
pushes the same events to every WebSocket client of the session.

### Error responses

Failures return a stable machine-readable code:

| HTTP | Code | Cause |
|---|---|---|
| `400` | `MALFORMED_EVENT` | Body is not a JSON object |
| `404` | `SESSION_NOT_FOUND` | Unknown `sessionId` |
| `409` | `SESSION_STOPPED` | Session was already stopped |
| `422` | `UNSUPPORTED_EVENT_TYPE` | `type` does not match the endpoint |
| `422` | `SCHEMA_VALIDATION_FAILED` | Field validation failed |
| `500` | `INTERNAL_ERROR` | Unhandled server fault |

## WebSocket

Connect to `ws://127.0.0.1:8000/ws/session/{session_id}`. On connect the server
immediately sends a `session` event with status `connected`, then streams
`transcript`, `claim`, `verification`, `error` and `session` events for that
session. Several clients may watch the same session. A client may send
`{"type":"ping"}` and receives `{"type":"pong"}`.

The server tolerates unexpected disconnects: a dead socket is dropped during
broadcast and never affects the other clients or the request that triggered
the send.

## Event contracts

Verdicts on the wire are **uppercase**: `TRUE`, `FALSE`, `UNVERIFIABLE`.

```json
{"type":"transcript","sessionId":"session_001","speaker":"Speaker 1",
 "text":"India won the 2011 Cricket World Cup.","timestamp":12.4,"isFinal":true}
```

```json
{"type":"claim","claimId":"claim_001","sessionId":"session_001","speaker":"Speaker 1",
 "timestamp":12.4,"claim":"India won the 2011 Cricket World Cup.",
 "claimType":"historical_fact"}
```

```json
{"type":"verification","claimId":"claim_001","sessionId":"session_001",
 "speaker":"Speaker 1","timestamp":12.4,"verdict":"TRUE",
 "reason":"India defeated Sri Lanka in the 2011 final.",
 "source":"https://example.com/source"}
```

```json
{"type":"error","sessionId":"session_001","code":"VERIFICATION_FAILED",
 "message":"Unable to verify the claim.","recoverable":true}
```

```json
{"type":"session","sessionId":"session_001","status":"connected"}
```

Error codes: `SESSION_NOT_FOUND`, `SESSION_STOPPED`, `SESSION_ALREADY_STOPPED`,
`SCHEMA_VALIDATION_FAILED`, `UNSUPPORTED_EVENT_TYPE`, `MALFORMED_EVENT`,
`VERIFICATION_FAILED`, `CLAIM_EXTRACTION_FAILED`, `BROADCAST_FAILED`,
`INTERNAL_ERROR`.

Unknown fields on inbound events are ignored (and logged) rather than
rejected, so a teammate adding a field cannot break the live demo.

## Adapter boundary

The backend never calls a model directly. `ClaimEngine` and `VerificationEngine`
are abstract interfaces, wired through `backend/adapters/`:

| Interface | Owner | Mock |
|---|---|---|
| `ClaimEngine.extract_claims(TranscriptEvent)` | Atif | `MockClaimEngine` |
| `VerificationEngine.verify(ClaimEvent)` | Nayanika | `MockVerificationEngine` |

Two additional bridges are provided:

* `VerificationServiceEngine` — wraps the existing `verification` package.
  Because that module's models do not declare `sessionId` and are strict
  (`extra="forbid"`), the bridge sends **only** the fields it accepts and
  re-attaches `sessionId` afterwards. `verification/models.py` is never edited.
* `UnavailableClaimEngine` / `UnavailableVerificationEngine` — selected when
  `USE_MOCK_ENGINES=false` before the real modules are integrated. They fail
  cleanly so a structured `error` event is emitted instead of a silent drop.

Verdict translation between the wire format and the internal module is
explicit and lives only in `backend/adapters/verification.py`:

| Wire | `verification` module |
|---|---|
| `TRUE` | `True` |
| `FALSE` | `False` |
| `UNVERIFIABLE` | `Unverifiable` |

## Mock pipeline

The whole pipeline runs with **no** AssemblyAI, LLM or search key:

```text
"India won the 2011 Cricket World Cup."   (Speaker 1, t=12.4)
  -> claim_001, claimType=historical_fact
  -> TRUE, "India defeated Sri Lanka in the 2011 final."
```

Try it end to end:

```bash
# 1. Start a session that replays the scripted demo
curl -X POST http://127.0.0.1:8000/session/start \
  -H "Content-Type: application/json" -d '{"startMockPipeline":true}'

# 2. Watch it
#    wscat -c ws://127.0.0.1:8000/ws/session/session_001
```

## Session storage

Sessions are held **in memory**. This is deliberate for the hackathon MVP and
means state is not shared between workers, is lost on restart, and the service
must run as a **single instance**. A shared store (Redis) would be required
before running multiple replicas.

## Logging

Structured logging with secret redaction, on the `live_fact_checker` logger
tree. `LOG_JSON=true` emits machine-readable JSON.

Every record passes a redaction filter that masks API keys, bearer tokens,
passwords, credentials embedded in URLs, and any structured field whose *name*
looks secret-shaped. Secrets are read from the environment only and are never
sent to the browser.

Trace labels emitted along the pipeline:

`TRANSCRIPT_RECEIVED`, `CLAIM_CREATED`, `VERIFICATION_STARTED`,
`VERIFICATION_COMPLETED`, `FRONTEND_BROADCAST`

## Backend tests

```bash
pytest -v                      # everything
pytest tests/backend -v        # backend only
pytest tests/test_verification.py -v   # verification module only
```

The backend suite covers session creation/retrieval/stop, health, transcript,
claim and verification validation, invalid verdicts, WebSocket connect,
disconnect and multi-client broadcast, malformed events, error events, the
mock pipeline, `claimId` and `sessionId` preservation, secret redaction and
production CORS rejection.

## Backend directory structure

```text
backend/
├── __init__.py
├── main.py              # app factory, CORS, WebSocket route, entry point
├── config.py            # settings from environment variables
├── logging_config.py    # structured logging + secret redaction
├── schemas.py           # the five external event contracts
├── session_manager.py   # in-memory sessions
├── websocket_manager.py # connection registry + broadcast
├── router.py            # event routing
├── routes/
│   ├── health.py
│   ├── session.py
│   └── events.py
├── adapters/
│   ├── claim_engine.py       # ClaimEngine interface + mock + unavailable
│   └── verification.py       # VerificationEngine + verdict translation
└── mocks/
    └── mock_stream.py        # MockClaimEngine, MockVerificationEngine, script
```

---

# Part 2 — Verification Module

This module implements the **Verification Subsystem** for the Live Fact-Checker project. It is responsible for taking extracted factual claims from live audio/speech transcripts, generating search queries, retrieving authoritative evidence, comparing statements against ground truth, and outputting structured verification results with source attribution and preserved claim tracking.

> **Note on verdict casing.** This module uses `True` / `False` /
> `Unverifiable`. The backend's external API and the frontend contract use
> uppercase `TRUE` / `FALSE` / `UNVERIFIABLE`. The conversion happens
> explicitly in `backend/adapters/verification.py`; this module is deliberately
> left unchanged. See Part 1, "Adapter boundary".

---

## Architecture & Pipeline Flow

The verification module executes a linear, decoupled pipeline:

```text
Claim Event
    │
    ▼
1. Query Generation (verification/query_generator.py)
   - Strips conversational speech prefixes, speaker tags, and filler words
   - Converts natural assertions into high-signal search queries
    │
    ▼
2. Evidence Retrieval (verification/retriever.py)
   - Retrieves authoritative evidence snippets via an abstract `EvidenceRetriever` interface
   - Ships with a zero-dependency `MockRetriever` for local offline testing
   - Implement the `EvidenceRetriever` interface to add a real search backend
    │
    ▼
3. Fact Checking & Stance Comparison (verification/checker.py)
   - Evaluates evidence stance, refutation markers, numerical figures, and consistency
   - Adheres to the principle: If evidence is missing, weak, or conflicting -> `Unverifiable`
   - Determines verdict (`True`, `False`, or `Unverifiable`)
   - Synthesizes concise reasoning and identifies primary source URL
    │
    ▼
4. Output Event Formulation (verification/service.py)
   - Returns a strictly validated `VerificationEvent`
   - Preserves original `claimId` throughout the entire pipeline
```

---

## Data Contracts

### 1. Input Contract: `ClaimEvent`

```json
{
  "type": "claim",
  "claimId": "claim_001",
  "speaker": "Speaker 1",
  "claim": "The company sold two million units.",
  "timestamp": 12.4
}
```

* **`type`**: Must be the literal string `"claim"`.
* **`claimId`**: Unique string identifier for the claim (must not be empty).
* **`speaker`**: Speaker identifier (e.g., `"Speaker 1"`).
* **`claim`**: Factual assertion extracted from speech.
* **`timestamp`**: Non-negative float representing the audio timestamp in seconds.

### 2. Output Contract: `VerificationEvent`

```json
{
  "type": "verification",
  "claimId": "claim_001",
  "verdict": "False",
  "reason": "The available source reports a different figure.",
  "source": "https://example.com"
}
```

* **`type`**: Must be the literal string `"verification"`.
* **`claimId`**: Preserved exact identifier from the corresponding `ClaimEvent`.
* **`verdict`**: Strict enumeration allowing only:
  * `"True"`
  * `"False"`
  * `"Unverifiable"`
* **`reason`**: Concise, human-readable rationale explaining the verdict.
* **`source`**: Authoritative URL or reference identifier.

---

## Directory Structure

```text
Live-Fact-Checker/
├── verification/
│   ├── __init__.py           # Package exports
│   ├── models.py             # Pydantic schemas (ClaimEvent, VerificationEvent, EvidenceItem)
│   ├── query_generator.py    # Speech artifact cleaning & query synthesis
│   ├── retriever.py          # EvidenceRetriever ABC + MockRetriever
│   ├── checker.py            # Comparison logic & 3-verdict determination
│   ├── service.py            # VerificationService orchestrator & CLI runner
│   └── mock_data.py          # Curated test datasets covering all edge cases
├── tests/
│   ├── __init__.py
│   └── test_verification.py  # Pytest test suite (contract, logic, edge cases)
├── .gitignore                # Git ignore rules (.venv, caches, env files)
├── requirements.txt          # Python dependencies (pydantic, pytest)
└── README.md                 # System documentation
```

---

## Running the Mock Verification Demo

To run the verification pipeline on sample mock claims covering all verdict types:

```bash
python verification/service.py
```

Or using module execution:

```bash
python -m verification.service
```

This will run through 6 distinct claim scenarios (clearly true, clearly false, numerical mismatch, unverifiable/no evidence, conflicting reports) and print the JSON `ClaimEvent` input and resulting `VerificationEvent` output for each.

---

## Running Automated Tests

Run the complete test suite with `pytest`:

```bash
pytest -v
```

### Test Coverage Highlights:
* **Contract Validation**: Verifies field constraints, non-empty validators, and rejection of malformed or extra fields.
* **Verdict Rules**: Asserts strict compliance with `"True"`, `"False"`, and `"Unverifiable"`.
* **`claimId` Preservation**: Ensures the ID passed into `verify_claim()` is identical in the returned `VerificationEvent`.
* **Query Cleaning**: Tests removal of speech filler (`"in my opinion"`, `"Speaker 1 said that"`).
* **Missing Evidence**: Guarantees unsupported/unseen claims return `"Unverifiable"` rather than guessing.
* **Conflicting Evidence**: Confirms that contradictory sources yield `"Unverifiable"`.
* **Numerical Fact Discrepancies**: Validates comparison between claimed figures and official figures.

---

## Teammate Integration: How Claim Extraction (Atif) Calls This Module

When Atif's claim extractor produces a claim event, it can be passed directly into `VerificationService`:

```python
from verification import VerificationService

service = VerificationService()

# 1. Using a raw dictionary:
claim_dict = {
    "type": "claim",
    "claimId": "claim_001",
    "speaker": "Speaker 1",
    "claim": "The company sold two million units.",
    "timestamp": 12.4
}

# Returns a VerificationEvent instance:
verification_event = service.verify_claim(claim_dict)
print(verification_event.claimId)   # "claim_001" (preserved)
print(verification_event.verdict)   # VerdictType.FALSE ("False")
print(verification_event.reason)    # Concise rationale
print(verification_event.source)    # Authoritative source URL

# 2. Or pure dict-in, dict-out:
result_dict = service.verify_claim_dict(claim_dict)
# result_dict is:
# {
#   "type": "verification",
#   "claimId": "claim_001",
#   "verdict": "False",
#   "reason": "...",
#   "source": "..."
# }
```

---

## Integrating Real Search Providers

To connect a live search API (e.g. Tavily, Google Custom Search, Serper, Bing) during later integration stages:

1. Provide `SEARCH_API_KEY` in `.env` (or pass `api_key` to `WebSearchRetriever`).
2. Alternatively, inject a custom `search_handler` callable directly into `WebSearchRetriever`:

```python
from verification import VerificationService, WebSearchRetriever

# Custom search function returning EvidenceItem objects:
retriever = WebSearchRetriever(api_key="your_api_key", search_handler=your_search_function)
service = VerificationService(retriever=retriever)

# Run verification - the verification logic remains completely unchanged!
result = service.verify_claim(claim_dict)
```

Read the API key from the environment; never hardcode it.

No modifications to `checker.py`, `models.py`, or `service.py` are needed when switching search backends.

