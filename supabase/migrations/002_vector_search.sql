-- 002_vector_search.sql
-- Vector index + similarity search for document_chunks.
-- Dimension 768 must match document_chunks.embedding in 001.

create extension if not exists vector with schema extensions;

-- HNSW + cosine distance (supported for up to 2000 dims; we use 768).
create index if not exists document_chunks_embedding_idx
  on public.document_chunks
  using hnsw (embedding extensions.vector_cosine_ops);

-- Returns the closest chunks from documents that are fully processed (status = 'ready').
-- similarity = 1 - cosine distance (1.0 = identical direction). Rows below
-- match_threshold are dropped; tune the threshold once you see real scores.
create or replace function public.match_document_chunks(
  query_embedding  extensions.vector(768),
  match_count      integer           default 5,
  match_threshold  double precision  default 0.5
)
returns table (
  chunk_id     uuid,
  document_id  uuid,
  filename     text,
  chunk_index  integer,
  content      text,
  similarity   double precision
)
language sql
stable
set search_path = public, extensions
as $$
  select
    c.id,
    c.document_id,
    d.filename,
    c.chunk_index,
    c.content,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.document_chunks c
  join public.documents d on d.id = c.document_id
  where d.status = 'ready'
    and 1 - (c.embedding <=> query_embedding) >= match_threshold
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 50);
$$;

-- Backend-only: not callable with the public anon/authenticated keys.
revoke all on function public.match_document_chunks(extensions.vector, integer, double precision)
  from public, anon, authenticated;
grant execute on function public.match_document_chunks(extensions.vector, integer, double precision)
  to service_role;
