-- Rode isso no SQL Editor do Supabase (depois do supabase-schema.sql)

create table if not exists whatsapp_config (
  id integer primary key default 1,
  webhook_url text,
  atualizado_em timestamptz not null default now(),
  constraint whatsapp_config_singleton check (id = 1)
);

create table if not exists whatsapp_numeros (
  id uuid primary key default gen_random_uuid(),
  numero text not null unique,
  criado_em timestamptz not null default now()
);
