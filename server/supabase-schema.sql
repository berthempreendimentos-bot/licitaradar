-- Rode isso no SQL Editor do seu projeto Supabase (Project > SQL Editor > New query)

create table if not exists pregoes_monitorados (
  id uuid primary key default gen_random_uuid(),
  id_compra text unique not null,
  uasg text,
  unidade text,
  orgao text,
  uf text,
  municipio text,
  numero_pregao text,
  ano_pregao integer,
  modalidade text,
  objeto text,
  situacao text,
  valor_estimado numeric,
  data_abertura timestamptz,
  data_encerramento timestamptz,
  link text,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create index if not exists pregoes_monitorados_uasg_idx on pregoes_monitorados (uasg);
