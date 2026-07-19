# RADAR — Monitoramento de Licitações (Compras.gov.br)

Sistema para cadastrar pregões eletrônicos do Compras.gov.br e acompanhar suas
atualizações (status, itens, resultado) e, quando houver sessão do ComprasNet
conectada, as mensagens da Sala de Disputa.

## Estrutura

- `server/` — API Node/Express + Prisma (SQLite) + scheduler + automação Playwright.
- `client/` — Frontend React (Vite).

## Como rodar

Em dois terminais:

```bash
cd server
npm install
npx prisma migrate dev   # primeira vez, cria o banco SQLite
npm run dev               # http://localhost:3001
```

```bash
cd client
npm install
npm run dev               # http://localhost:5173 (com proxy /api -> :3001)
```

Abra http://localhost:5173.

## Fluxo

1. Na tela principal, busque um pregão por UASG (+ opcionalmente o número do
   pregão) e clique em "Monitorar" para adicionar à lista.
2. O painel abaixo lista os pregões monitorados, com abas Monitorando / Não
   Monitoradas / Favoritas, filtros e ações (favoritar, atribuir responsável,
   remover, marcar mensagens como lidas).
3. Um job em background (a cada `POLL_INTERVAL_MINUTES`, padrão 10) reconsulta
   a API pública para detectar mudanças de status/resultado em cada pregão
   monitorado.

## Login com certificado digital A1

Se a empresa tem um certificado A1 (arquivo `.pfx`/`.p12`), o sistema usa esse
certificado para logar no ComprasNet **sem precisar digitar CPF nem senha**.

**Importante (achado em teste real, corrige uma suposição inicial errada):**
o gov.br mostra um captcha visual (hCaptcha, tipo "clique nos objetos que
produzem música") no meio do login — **mesmo usando certificado**. Isso
significa que login 100% automático/headless (sem ninguém olhando) **não é
possível**, e este sistema não tenta resolver esse captcha sozinho (seria
contornar uma proteção anti-bot do gov.br, o que está fora do escopo). Por
isso, clicar em "Logar com certificado" sempre abre uma janela de navegador
de verdade na tela do servidor: com certificado configurado, o sistema já
clica em "Entrar com Gov.br" → "Seu certificado digital" sozinho, e você só
precisa resolver o captcha que aparece; sem certificado, você conduz o login
inteiro (CPF/senha, 2FA, o que pedir). Depois disso a sessão fica salva e é
reaproveitada pelo scheduler até expirar.

**Pela tela (recomendado):** clique em "⚙️ Certificado" no topo da tela,
selecione o arquivo `.pfx`/`.p12` e digite a senha, depois "Salvar
certificado". O arquivo é salvo em `server/uploads/certificado.pfx` (fora do
git) e a senha é criptografada (AES-256-GCM) antes de ir para o banco — nunca
fica em texto puro, nem é devolvida pela API depois de salva. A chave de
criptografia é gerada automaticamente na primeira vez e guardada em
`server/.chave-local` (também fora do git).

**Alternativa por arquivo `.env`** (para quem prefere apontar direto para um
certificado que já existe na máquina, sem passar pela tela):

```
CERT_PFX_PATH=C:\caminho\para\seu-certificado.pfx
CERT_PFX_PASSPHRASE=sua-senha-do-certificado
```

Se um certificado foi enviado pela tela, ele tem prioridade sobre o `.env`.

**Nunca coloque o arquivo `.pfx` dentro da pasta do projeto manualmente nem
faça commit dele, do `.env` ou de `server/.chave-local`** — todos já estão no
`.gitignore`, mas o cuidado ao mover/copiar arquivos é seu também.

O fluxo de login foi mapeado e confirmado direto no site real (sem precisar de
credencial, só inspecionando HTML/JS público):

1. `https://www.comprasnet.gov.br/seguro/loginPortalFornecedor.asp` → botão
   **"Entrar com Gov.br"** → navega para `sso.acesso.gov.br`.
2. Nessa página existe o botão **"Seu certificado digital"**
   (`#login-certificate`), cujo `formaction` aponta para
   `https://certificado.sso.acesso.gov.br/login` — **esse é o domínio exato
   que faz o handshake TLS com o certificado do cliente** (confirmado: sem
   certificado, esse endpoint devolve 302 para `acesso.gov.br/info/x509/`, e
   com uma sessão real o navegador trava esperando a escolha de certificado —
   exatamente o que o `clientCertificates` do Playwright resolve
   automaticamente, sem diálogo).
3. Sucesso = o fluxo retorna para `comprasnet.gov.br` (fora de
   `loginPortal*.asp`). Falha = volta para `acesso.gov.br/info/x509/` ou trava
   nesse passo (certificado inválido/vencido/não confiável).

Isso está implementado em `server/src/services/comprasnetAuth.js`
(`iniciarLogin`). Quando a sessão expira, o scheduler (`server/src/scheduler.js`)
**não** tenta relogar sozinho (não tem como, por causa do captcha) — ele só
pula a checagem de mensagens naquele ciclo. O status "Sessão ComprasNet
inativa" na tela avisa que é preciso clicar em "Logar com
certificado"/"Conectar ComprasNet" de novo.

Se `CERT_ORIGENS` (a lista de domínios ligados ao certificado) precisar
mudar no futuro — por exemplo se o gov.br trocar de subdomínio — ajuste a
variável no `.env`; o valor padrão já cobre o fluxo confirmado acima.

## Sobre as mensagens da Sala de Disputa

A API pública do Compras.gov.br **não expõe** as mensagens do chat da Sala de
Disputa — isso foi confirmado inspecionando diretamente o spec OpenAPI de
`dadosabertos.compras.gov.br`. A única forma de acessar essas mensagens é
logado como fornecedor no ComprasNet.

Por isso, o botão **"Conectar ComprasNet"** no topo da tela abre uma janela de
navegador (Playwright, não headless) para você fazer login manualmente —
inclusive resolver CAPTCHA/2FA do gov.br, que não pode ser automatizado. Depois
do login, a sessão fica salva e é reaproveitada pelo scheduler para consultar
as mensagens dos pregões monitorados, até expirar (então será preciso logar de
novo).

**Importante:** o serviço `server/src/services/comprasnetMessages.js` que lê as
mensagens foi implementado por heurística (intercepta respostas JSON da SPA do
ComprasNet cuja URL contenha "mensagem/chat/disputa"), já que o formato exato
da API interna da Sala de Disputa só pode ser confirmado inspecionando o
tráfego de rede numa sessão logada real. Pode ser necessário ajustar esse
arquivo depois do primeiro login real, observando no DevTools do navegador
qual chamada de rede a SPA faz para carregar as mensagens.

## Fonte de dados

- Busca e status dos pregões: `modulo-contratacoes/1_consultarContratacoes_PNCP_14133`
  (API pública, Lei 14.133/PNCP), filtrando por `unidadeOrgaoCodigoUnidade`
  (UASG) e `codigoModalidade=5` (Pregão Eletrônico). Esse endpoint foi validado
  contra a API real durante o desenvolvimento.
- O endpoint equivalente do módulo legado (`modulo-legado/3_consultarPregoes`)
  tem um bug no próprio backend do governo ao filtrar por UASG (erro interno
  "Could not resolve attribute coUasg") — por isso não é usado.

## Fora de escopo (v1)

- Outros portais além do Compras.gov.br.
- Autenticação de usuários do próprio sistema (responsáveis são só uma lista
  de nomes, sem login).
- Notificações por e-mail/push.
- Resolução automática de CAPTCHA (sempre manual).
