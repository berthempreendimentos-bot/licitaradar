-- Rode isso no SQL Editor do Supabase

alter table pregoes_monitorados
  add column if not exists favorito boolean not null default false;

create index if not exists pregoes_monitorados_favorito_idx on pregoes_monitorados (favorito);
