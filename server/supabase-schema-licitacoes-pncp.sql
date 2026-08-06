-- Rode isso no SQL Editor do Supabase (Project > SQL Editor > New query)

create table if not exists licitacoes_pncp (
  id_compra text primary key,
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
  dados_completos jsonb not null default '{}'::jsonb,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

-- Índices para otimizar as buscas frequentes
create index if not exists licitacoes_pncp_uf_idx on licitacoes_pncp (uf);
create index if not exists licitacoes_pncp_municipio_idx on licitacoes_pncp (municipio);
create index if not exists licitacoes_pncp_data_abertura_idx on licitacoes_pncp (data_abertura);
create index if not exists licitacoes_pncp_valor_estimado_idx on licitacoes_pncp (valor_estimado);
