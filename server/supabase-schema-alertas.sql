-- Rode isso no SQL Editor do Supabase (depois do supabase-schema.sql e supabase-schema-mensagens.sql)

create table if not exists palavras_monitoradas (
  id uuid primary key default gen_random_uuid(),
  termo text not null unique,
  criado_em timestamptz not null default now()
);

create table if not exists alertas_gerados (
  id uuid primary key default gen_random_uuid(),
  id_compra text not null references pregoes_monitorados (id_compra) on delete cascade,
  mensagem_id uuid references mensagens_chat (id) on delete cascade,
  palavra_encontrada text not null,
  lido boolean not null default false,
  criado_em timestamptz not null default now()
);

create index if not exists alertas_gerados_lido_idx on alertas_gerados (lido);
create index if not exists alertas_gerados_id_compra_idx on alertas_gerados (id_compra);
