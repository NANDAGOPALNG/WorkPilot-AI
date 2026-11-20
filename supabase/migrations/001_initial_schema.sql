-- 001_initial_schema.sql
-- WorkPilot AI MVP schema.
-- Embedding dimension: 768 (Gemini gemini-embedding-001 with output_dimensionality=768).
-- If you change the embedding model/dimension, change it here AND in 002_vector_search.sql.

-- pgvector is needed here because document_chunks has a vector column.
create extension if not exists vector with schema extensions;

-- Shared trigger function: keeps updated_at current on UPDATE.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- 1. documents ---------------------------------------------------------
create table public.documents (
  id            uuid primary key default gen_random_uuid(),
  filename      text not null,
  file_type     text not null,
  storage_path  text not null unique,
  file_size     bigint not null default 0 check (file_size >= 0),
  status        text not null default 'uploaded'
                check (status in ('uploaded', 'processing', 'ready', 'failed')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index documents_status_idx     on public.documents (status);
create index documents_created_at_idx on public.documents (created_at desc);

create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function public.set_updated_at();

-- 2. document_chunks ---------------------------------------------------
create table public.document_chunks (
  id           uuid primary key default gen_random_uuid(),
  document_id  uuid not null references public.documents (id) on delete cascade,
  chunk_index  integer not null check (chunk_index >= 0),
  content      text not null,
  embedding    extensions.vector(768) not null,
  created_at   timestamptz not null default now(),
  unique (document_id, chunk_index)   -- also serves as the document_id lookup index
);

-- 3. tickets -----------------------------------------------------------
create sequence public.ticket_number_seq start with 1001;

create table public.tickets (
  id             uuid primary key default gen_random_uuid(),
  ticket_number  text not null unique
                 default ('TKT-' || nextval('public.ticket_number_seq')::text),
  title          text not null,
  description    text not null default '',
  category       text not null default 'general',
  priority       text not null default 'medium'
                 check (priority in ('low', 'medium', 'high', 'critical')),
  status         text not null default 'open'
                 check (status in ('open', 'in_progress', 'resolved', 'closed')),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index tickets_status_idx     on public.tickets (status);
create index tickets_created_at_idx on public.tickets (created_at desc);

create trigger tickets_set_updated_at
  before update on public.tickets
  for each row execute function public.set_updated_at();

-- 4. generated_documents -----------------------------------------------
create table public.generated_documents (
  id                 uuid primary key default gen_random_uuid(),
  title              text not null,
  document_type      text not null,   -- e.g. 'incident_report', 'technical_summary'
  content            text not null,
  related_ticket_id  uuid references public.tickets (id) on delete set null,
  created_at         timestamptz not null default now()
);

create index generated_documents_ticket_idx     on public.generated_documents (related_ticket_id);
create index generated_documents_created_at_idx on public.generated_documents (created_at desc);

-- 5. conversations -----------------------------------------------------
create table public.conversations (
  id          uuid primary key default gen_random_uuid(),
  session_id  text not null,
  created_at  timestamptz not null default now()
);

create index conversations_session_idx on public.conversations (session_id);

-- 6. conversation_messages ---------------------------------------------
create table public.conversation_messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.conversations (id) on delete cascade,
  role             text not null check (role in ('user', 'assistant', 'system', 'tool')),
  content          text not null,
  created_at       timestamptz not null default now()
);

create index conversation_messages_conv_idx
  on public.conversation_messages (conversation_id, created_at);

-- Security --------------------------------------------------------------
-- RLS on with NO policies = the public anon/authenticated keys can't touch these
-- tables. Only the backend (service_role key, which bypasses RLS) has access.
alter table public.documents              enable row level security;
alter table public.document_chunks        enable row level security;
alter table public.tickets                enable row level security;
alter table public.generated_documents    enable row level security;
alter table public.conversations          enable row level security;
alter table public.conversation_messages  enable row level security;
