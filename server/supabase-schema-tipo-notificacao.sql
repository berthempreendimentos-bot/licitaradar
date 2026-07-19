-- Rode isso no SQL Editor do Supabase

alter table palavras_monitoradas
  add column if not exists tipo_notificacao text not null default 'padrao';

alter table alertas_gerados
  add column if not exists tipo_notificacao text not null default 'padrao';
