# WorkPilot AI

**A voice-first enterprise AI assistant.** Employees talk to WorkPilot to get answers from company documents, raise and track support tickets, and generate incident reports, all by voice or through a web dashboard.

> Built for a hackathon as an MVP. See [Project status](#project-status) and [Security notes](#security-notes) before deploying anywhere public.

---

## Table of contents

- [Features](#features)
- [Project status](#project-status)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository structure](#repository-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Running the voice assistant locally](#running-the-voice-assistant-locally)
- [API overview](#api-overview)
- [Testing](#testing)
- [Security notes](#security-notes)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Voice assistant.** Real-time spoken conversation powered by Agora Conversational AI. The agent can call WorkPilot's backend as tools during a conversation.
- **Knowledge Base (RAG).** Upload PDF, TXT or DOCX files. Documents are extracted, chunked and embedded, and answers are grounded in the retrieved text with numbered source citations. If the documents don't cover a question, the assistant says so instead of guessing.
- **Support tickets.** Create tickets by voice with an explicit confirmation step, then track them in a dashboard with status and priority counts, filters, search, paging, a detail view and inline status/priority updates.
- **Generated documents.** The backend can produce incident reports and technical summaries from facts the user supplies. Missing facts are marked "Not provided", never invented.
- **Unified agent tool layer.** One set of backend tools (`search_knowledge`, `create_ticket`, `get_ticket_status`, `generate_document`) used by the voice agent, with a consistent success/failure response envelope.

## Project status

| Area | Status |
| --- | --- |
| Supabase schema, vector search | Done |
| Document ingestion (extract, chunk, embed) and RAG answering | Done |
| Knowledge Base UI (upload, list, delete) | Done |
| Tickets API and dashboard UI | Done |
| Generated-documents API | Done |
| Agent tool layer and Agora custom tools | Done |
| Voice assistant UI | Done |
| Documentation page (view generated documents) | **Not built yet.** The page is a placeholder; documents are saved by the backend but not yet browsable in the UI |
| Authentication / RBAC | Not implemented (see [Security notes](#security-notes)) |

## Architecture

```
┌────────────────────┐   REST    ┌──────────────────────────┐
│  React + Vite SPA  │ ────────▶ │      FastAPI backend     │
│  (dashboard + mic) │           │                          │
└─────────┬──────────┘           │  /api/documents          │
          │ RTC audio            │  /api/knowledge/ask      │
          ▼                      │  /api/tickets            │
┌────────────────────┐  HTTPS    │  /api/generated-documents│
│ Agora Conversational│ ───────▶ │  /api/agent/tools/*      │
│ AI (ASR + LLM + TTS)│  tools   │  /api/agora/sessions     │
└────────────────────┘           └───────┬───────────┬──────┘
                                         │           │
                                         ▼           ▼
                                 ┌────────────┐  ┌──────────┐
                                 │  Supabase  │  │  Gemini  │
                                 │ Postgres + │  │ embeddings│
                                 │ pgvector + │  │ + answers │
                                 │  Storage   │  └──────────┘
                                 └────────────┘
```

**How a voice question flows:** the browser joins an Agora channel → the agent transcribes speech and decides to call `searchKnowledge` → Agora calls the backend's `/api/agent/tools/search_knowledge` over public HTTPS with a shared-secret header → the backend embeds the question, runs a pgvector similarity search, asks Gemini for a grounded answer and returns it with sources → the agent speaks the answer.

The tool endpoints only call existing services (`rag_service`, `ticket_service`, `documentation_service`), so the web UI and the voice agent share one implementation.

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python, FastAPI, Pydantic |
| Frontend | React, Vite, React Router, Axios, lucide-react |
| Database | Supabase PostgreSQL with pgvector, Supabase Storage |
| AI | Google Gemini (embeddings and answer generation) |
| Voice | Agora Conversational AI (managed ASR, LLM and TTS) and the Agora RTC Web SDK |

## Repository structure

```
WorkPilot-AI/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # HTTP routes (documents, knowledge, tickets, agent tools, agora, ...)
│   │   ├── core/             # settings, database client, security helpers
│   │   ├── integrations/     # Agora, Gemini and Supabase clients
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── services/         # business logic (RAG, retrieval, tickets, Agora session/tools, ...)
│   │   └── utils/            # file validation, text extraction, chunking
│   ├── tests/                # pytest suite (uses an in-memory Supabase fake)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/       # layout, ui, voice, knowledge, tickets
│   │   ├── hooks/            # useAgora, useDocuments, useTickets
│   │   ├── pages/            # Assistant, KnowledgeBase, Tickets, Documentation
│   │   └── services/         # API clients
│   └── .env.example
├── supabase/
│   ├── migrations/           # 001 schema, 002 vector search
│   └── seed.sql
└── docs/                     # architecture and demo notes
```

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- A [Supabase](https://supabase.com) project
- A [Gemini API key](https://aistudio.google.com/apikey)
- An [Agora](https://www.agora.io) project with Conversational AI enabled (only needed for voice)
- A public HTTPS tunnel such as [ngrok](https://ngrok.com) (only needed for voice, see below)

### 1. Database

In the Supabase SQL editor, run in order:

1. `supabase/migrations/001_initial_schema.sql`
2. `supabase/migrations/002_vector_search.sql`
3. Optionally `supabase/seed.sql`

The documents bucket (default name `knowledge-documents`) must exist in Supabase Storage.

### 2. Backend

```bash
cd backend
python -m venv venv
# macOS/Linux:   source venv/bin/activate
# Windows (PS):  .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
# edit .env (see Configuration)
uvicorn app.main:app --reload --port 8000
```

The API is now at http://localhost:8000, with interactive docs at http://localhost:8000/docs. Check connectivity with `http://localhost:8000/health?check_db=true`.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env        # Windows: copy .env.example .env
npm run dev
```

Open http://localhost:5173. The dev server is pinned to port 5173 because the backend's CORS allow-list is `http://localhost:5173`.

## Configuration

### Backend (`backend/.env`)

| Variable | Required | Description |
| --- | --- | --- |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Service-role key. **Backend only, never expose it to the frontend** |
| `SUPABASE_STORAGE_BUCKET` | No | Storage bucket for uploads (default `knowledge-documents`) |
| `GEMINI_API_KEY` | For KB | Needed for ingestion and question answering |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | No | Default `gemini-embedding-001` / `768`. The dimension must stay 768 to match the SQL schema |
| `LLM_MODEL` | No | Gemini model used to write answers (default `gemini-2.5-flash`) |
| `RETRIEVAL_TOP_K` | No | Chunks retrieved per question (default 5) |
| `RETRIEVAL_THRESHOLD` | No | Minimum cosine similarity, 0 to 1 (default 0.5). Lower it if relevant questions return "no answer" |
| `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE` | For voice | Agora project credentials (32 hex characters each) |
| `AGORA_CUSTOMER_ID`, `AGORA_CUSTOMER_SECRET` | For voice | Agora RESTful API credentials |
| `AGORA_TOOLS_BASE_URL` | For voice | Public **HTTPS** origin of this backend (no trailing path) |
| `AGORA_TOOLS_SHARED_SECRET` | For voice | 16+ visible characters. Agora sends it in `X-WorkPilot-Tool-Secret`; the backend rejects tool calls without it |

Generate a shared secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Frontend (`frontend/.env`)

| Variable | Description |
| --- | --- |
| `VITE_API_BASE_URL` | Backend URL (default `http://localhost:8000`) |
| `VITE_AGORA_APP_ID` | Agora App ID (public identifier) |

> Never commit `.env` files. Only `.env.example` is tracked.

## Running the voice assistant locally

Agora's cloud calls your backend's tool endpoints, so `localhost` will not work. Expose the backend over HTTPS:

```bash
ngrok http 8000
```

1. Copy the `https://…` forwarding URL into `AGORA_TOOLS_BASE_URL` in `backend/.env`.
2. Set `AGORA_TOOLS_SHARED_SECRET`.
3. **Restart the backend**, then start a **new** voice session from the Assistant page. A running agent keeps the URL and secret it was started with.

Try asking about an uploaded document ("What does our IT policy say about password length?"), or say "I need to raise a ticket about my VPN".

## API overview

Full, interactive documentation is available at `/docs` when the backend is running.

| Area | Endpoints |
| --- | --- |
| Health | `GET /health` (`?check_db=true` to verify Supabase) |
| Documents | `POST /api/documents/upload` · `GET /api/documents` · `DELETE /api/documents/{id}` |
| Knowledge | `POST /api/knowledge/ask` |
| Tickets | `GET /api/tickets` (`status`, `priority`, `limit`, `offset`) · `GET /api/tickets/{id}` · `POST /api/tickets` · `PATCH /api/tickets/{id}` |
| Generated documents | `POST /api/generated-documents` · `GET /api/generated-documents` · `GET /api/generated-documents/{id}` |
| Voice sessions | `POST /api/agora/sessions` · `POST /api/agora/sessions/{id}/stop` |
| Agent tools | `GET /api/agent/tools` · `POST /api/agent/tools/{search_knowledge, create_ticket, get_ticket_status, generate_document}` |

Ticket statuses are `open`, `in_progress`, `resolved`, `closed`; priorities are `low`, `medium`, `high`, `critical`. Ticket IDs, numbers and timestamps are generated by the database and cannot be modified through the API.

Uploads accept PDF, TXT and DOCX up to 10 MB. Scanned or image-only PDFs are not supported.

## Testing

```bash
# Backend
cd backend
pip install pytest
python -m pytest -q

# Frontend
cd frontend
npm run lint
npm run build
```

The backend tests run without any real Supabase, Gemini or Agora credentials; they use an in-memory fake database and mocked providers.

## Security notes

This is an MVP and is **not production-ready**.

- There is no user authentication or RBAC. The REST API, including voice session start/stop, is open to anyone who can reach it.
- The agent tool routes are protected only by the shared secret. Always set `AGORA_TOOLS_SHARED_SECRET` before exposing the backend through a public URL.
- CORS allows only `http://localhost:5173`; update it for any deployed frontend.
- Keep the Supabase service-role key, Agora certificate and customer secret on the backend only. Backend logs are written to avoid secrets and full document contents.

Add authentication, rate limiting and a restricted CORS policy before any public deployment.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Voice session won't start (503) | Read the backend log; it names the missing or invalid `AGORA_*` variable. `AGORA_TOOLS_BASE_URL` must be a public `https://` URL |
| Agent says documents don't cover a question you know they do | Confirm the document status is `ready` and chunks exist. Test `POST /api/knowledge/ask` directly, and try a lower `RETRIEVAL_THRESHOLD` |
| Tool calls return HTTP 401 | `AGORA_TOOLS_SHARED_SECRET` changed. Restart the backend and start a new voice session |
| No `search_knowledge called` line in the backend log | Agora is not calling the tool. Check the ngrok URL is current and start a new session |
| Frontend shows "Cannot reach the WorkPilot backend" | Backend not running, or `VITE_API_BASE_URL` is wrong |
| Dev server fails to start on port 5173 | Another process holds the port. The backend's CORS only allows 5173, so free it rather than change it |

## License

No license has been specified for this project yet. Add a `LICENSE` file before sharing or accepting contributions.