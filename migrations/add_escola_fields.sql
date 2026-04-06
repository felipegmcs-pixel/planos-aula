-- Migração: Adicionar campos de escola ao perfil do professor
-- Data: 2026-04-06
-- Descrição: Permite que cada professor cadastre os dados da sua escola,
--            que serão usados automaticamente na geração de planos de aula.

ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_governo TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_secretaria TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_diretoria TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_nome TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_endereco TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_fone TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_email TEXT DEFAULT '';
