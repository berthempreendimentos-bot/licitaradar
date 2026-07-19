-- Rode isso no SQL Editor do Supabase (depois do supabase-schema.sql já ter sido executado)

create table if not exists mensagens_chat (
  id uuid primary key default gen_random_uuid(),
  id_compra text not null references pregoes_monitorados (id_compra) on delete cascade,
  remetente text,
  grupo text,
  mensagem text not null,
  data_hora_texto text,
  data_hora timestamptz,
  capturado_em timestamptz not null default now(),
  unique (id_compra, remetente, mensagem, data_hora_texto)
);

create index if not exists mensagens_chat_id_compra_idx on mensagens_chat (id_compra);
