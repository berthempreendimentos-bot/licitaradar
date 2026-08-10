-- Rode isso no SQL Editor do Supabase

alter table pregoes_monitorados
  add column if not exists fase_producao text;

create index if not exists pregoes_monitorados_fase_producao_idx on pregoes_monitorados (fase_producao);
