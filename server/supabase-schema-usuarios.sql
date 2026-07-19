-- Rode isso no SQL Editor do Supabase

create table if not exists usuarios (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  senha_hash text not null,
  criado_em timestamptz not null default now()
);
