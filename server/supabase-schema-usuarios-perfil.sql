-- Rode isso no SQL Editor do Supabase
-- Perfil de administrador alteravel pela tela de usuarios (usuarios.html).

alter table usuarios add column if not exists admin boolean not null default false;
