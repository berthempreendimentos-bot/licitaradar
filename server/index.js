require('dotenv/config');
const express = require('express');
const cookieSession = require('cookie-session');
const bcrypt = require('bcryptjs');
const path = require('path');
const { getSupabase } = require('./src/supabaseClient');

const app = express();
const PORT = process.env.PORT || 3001;

const ROTAS_PUBLICAS = new Set(['/login.html', '/api/login', '/style.css', '/licitacao-compartilhada.html']);

const ESFERA_LABELS = { F: 'Federal', E: 'Estadual', M: 'Municipal', D: 'Distrital' };

// Fases do quadro de Produção (kanban), na ordem em que aparecem no board.
// Favoritar uma licitação (ver PATCH /api/monitorados/:idCompra/favorito) entra
// automaticamente na primeira fase.
const FASES_PRODUCAO = ['participacao', 'proposta', 'habilitacao', 'diligencia', 'homologacao'];
const FASE_PRODUCAO_INICIAL = FASES_PRODUCAO[0];

function mapEsfera(esferaId) {
  return ESFERA_LABELS[esferaId] || null;
}

// Remove acentos/cedilha pra busca de cidade não depender de digitar "Brasília"
// certinho — "brasilia", "Brasilia" ou "BRASÍLIA" devem bater igual.
function removerAcentos(texto) {
  return String(texto || '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();
}

function derivarPortal(link) {
  if (!link) return null;
  let host;
  try {
    host = new URL(link).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
  if (host.includes('serpro.gov.br') || host.includes('comprasnet')) return 'ComprasNet';
  if (host.includes('bb.com.br')) return 'Licitações-e (BB)';
  if (host.includes('bbmnetlicitacoes')) return 'BBMNET';
  if (host.includes('bllcompras')) return 'BLL Compras';
  if (host.includes('pncp.gov.br')) return 'PNCP';
  if (host.includes('compras.gov.br')) return 'Compras.gov.br';
  return host;
}

// numeroControlePNCP tem o formato {cnpj}-{tipo}-{sequencial}/{ano}, ex.:
// "11151460000137-1-000033/2026". Vários registros usam esse valor como id_compra.
const REGEX_NUMERO_CONTROLE_PNCP = /^(\d{14})-\d+-(\d+)\/(\d{4})$/;

// Extrai cnpj/ano/sequencial da compra. Tenta primeiro os campos planos do
// dados_completos (import antigo via compras.gov.br) e, se não existirem, extrai
// diretamente do id_compra (formato numeroControlePNCP).
function extrairCnpjAnoSequencial(dadosCompletos, idCompra) {
  let cnpj = dadosCompletos?.orgaoEntidadeCnpj;
  let ano = dadosCompletos?.anoCompraPncp;
  let sequencial = dadosCompletos?.sequencialCompraPncp;

  if ((!cnpj || !ano || !sequencial) && idCompra) {
    const match = REGEX_NUMERO_CONTROLE_PNCP.exec(idCompra);
    if (match) {
      cnpj = match[1];
      sequencial = Number(match[2]);
      ano = match[3];
    }
  }

  if (!cnpj || !ano || !sequencial) return null;
  return { cnpj, ano, sequencial: Number(sequencial) };
}

// Fallback pra quando não existe link salvo pro portal de origem: manda pra
// página da compra no próprio Portal PNCP.
function construirLinkPortalPncp(info) {
  if (!info) return null;
  return `https://pncp.gov.br/app/editais/${info.cnpj}/${info.ano}/${info.sequencial}`;
}

// Monta o formato de licitação usado tanto na busca autenticada quanto na página
// pública de compartilhamento — mantém as duas fontes em sincronia.
function mapearLicitacao(row) {
  const infoPncp = extrairCnpjAnoSequencial(row.dados_completos, row.id_compra);
  // O link antigo do ComprasNet (cnetmobile) hoje cai na home genérica de
  // comprasgovernamentais.gov.br em vez de abrir a compra específica. A página
  // da compra no PNCP (montada a partir de cnpj/ano/sequencial) é confiável e
  // sempre existe pra qualquer compra publicada no PNCP, então tem prioridade.
  const linkFinal = construirLinkPortalPncp(infoPncp) || row.link;

  return {
    idCompra: row.id_compra,
    uasg: row.uasg,
    unidade: row.unidade,
    orgao: row.orgao,
    uf: row.uf,
    municipio: row.municipio,
    numeroPregao: row.numero_pregao,
    anoPregao: row.ano_pregao,
    modalidade: row.modalidade,
    objeto: row.objeto,
    situacao: row.situacao,
    valorEstimado: row.valor_estimado,
    dataAbertura: row.data_abertura,
    dataEncerramento: row.data_encerramento,
    link: linkFinal,
    esfera: mapEsfera(row.dados_completos?.orgaoEntidadeEsferaId),
    portal: derivarPortal(linkFinal),
    linkArquivos: infoPncp
      ? `/api/licitacoes/${encodeURIComponent(row.id_compra)}/arquivo`
      : null,
    criadoEm: row.criado_em,
    atualizadoEm: row.atualizado_em,
  };
}

function exigirLogin(req, res, next) {
  if (ROTAS_PUBLICAS.has(req.path)) return next();
  
  // Permite que o robô (Python/JS) envie mensagens e consulte a lista sem precisar de sessão
  if (req.path.startsWith('/api/mensagens/') && req.method === 'POST') return next();
  if (req.path === '/api/monitorados' && req.method === 'GET') return next();
  if (req.path === '/api/bot/alerta' && req.method === 'POST') return next();
  // O robo marca a licitacao como revogada quando a pagina de mensagens nao abre
  // (ver marcar_como_revogada em monitor_mensagens.py) - tambem sem sessao de usuario.
  if (/^\/api\/monitorados\/[^/]+\/situacao$/.test(req.path) && req.method === 'PATCH') return next();
  // Página de compartilhamento (licitacao-compartilhada.html): dados de uma única
  // licitação e o download do edital ficam públicos pra quem recebe o link poder
  // ver sem precisar de conta — mesma informação que já é pública no PNCP.
  if (req.path.startsWith('/api/publico/') && req.method === 'GET') return next();
  if (/^\/api\/licitacoes\/[^/]+\/arquivo$/.test(req.path) && req.method === 'GET') return next();

  if (req.session && req.session.usuarioId) return next();
  if (req.path.startsWith('/api/')) {
    return res.status(401).json({ erro: 'Não autenticado.' });
  }
  return res.redirect('/login.html');
}

const PNCP_API = 'https://dadosabertos.compras.gov.br/modulo-contratacoes/1_consultarContratacoes_PNCP_14133';
const MODALIDADE_PREGAO_ELETRONICO = 5;
const JANELAS_DE_1_ANO = 3; // a API não aceita intervalo de datas maior que 365 dias
const MAX_PAGINAS_POR_JANELA = 2;
const TAMANHO_PAGINA = 500;

function formatarData(data) {
  return data.toISOString().slice(0, 10);
}

// UASG sempre tem 6 dígitos e muitas começam com zero (ex.: 070011). Sem completar
// com zero à esquerda, a API do governo trata "70011" como um código diferente de
// "070011" e simplesmente não devolve nenhum resultado (parece bug de busca, mas é
// só o zero que falta).
function normalizarUasg(valor) {
  const digitos = String(valor || '').replace(/\D/g, '');
  if (!digitos) return '';
  return digitos.length < 6 ? digitos.padStart(6, '0') : digitos;
}

// Aceita formatos como "90067", "90067/2026", "090067-2026" ou colado "900672026"
function normalizarNumeroPregao(valor) {
  if (!valor) return null;
  const limpo = String(valor).trim();

  const comSeparador = limpo.match(/^(\d+)\D+(\d{4})$/);
  if (comSeparador) {
    return { numero: comSeparador[1].replace(/^0+/, '') || '0', ano: Number(comSeparador[2]) };
  }

  const soDigitos = limpo.match(/^(\d+)$/);
  if (soDigitos) {
    const digitos = soDigitos[1];
    if (digitos.length > 4) {
      const possivelAno = Number(digitos.slice(-4));
      if (possivelAno >= 2000 && possivelAno <= 2099) {
        const numero = digitos.slice(0, -4).replace(/^0+/, '') || '0';
        return { numero, ano: possivelAno };
      }
    }
    return { numero: digitos.replace(/^0+/, '') || '0', ano: null };
  }

  return null;
}

const { parseMensagensColadas, verificarPalavrasChave } = require('./src/utils/mensagens');
const { notificarWhatsapp, testarWebhook } = require('./src/services/whatsappWebhook');
const roboLocal = require('./src/services/roboLocal');

app.use(express.json());
app.use(
  cookieSession({
    name: 'session',
    secret: process.env.SESSION_SECRET || 'senha_secreta_fallback',
    maxAge: 8 * 60 * 60 * 1000,
    httpOnly: true,
    sameSite: 'lax',
  })
);

app.post('/api/login', async (req, res) => {
  const email = String((req.body || {}).email || '').trim().toLowerCase();
  const senha = String((req.body || {}).senha || '');

  if (!email || !senha) {
    return res.status(400).json({ erro: 'Informe e-mail e senha.' });
  }

  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('usuarios')
      .select('id, email, senha_hash')
      .eq('email', email)
      .maybeSingle();

    if (error) throw error;
    if (!data) {
      return res.status(401).json({ erro: 'E-mail ou senha inválidos.' });
    }

    const senhaCorreta = await bcrypt.compare(senha, data.senha_hash);
    if (!senhaCorreta) {
      return res.status(401).json({ erro: 'E-mail ou senha inválidos.' });
    }

    req.session.usuarioId = data.id;
    req.session.usuarioEmail = data.email;
    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro no login:', erro.message);
    res.status(500).json({ erro: 'Não foi possível autenticar agora.' });
  }
});

app.post('/api/logout', (req, res) => {
  req.session = null;
  res.json({ ok: true });
});

app.get('/api/me', (req, res) => {
  if (req.session && req.session.usuarioId) {
    return res.json({ autenticado: true, email: req.session.usuarioEmail });
  }
  res.status(401).json({ autenticado: false });
});

app.use(exigirLogin);
app.use(express.static(path.join(__dirname, '..')));
// Nota: a rota /contratacoes (server/src/routes.js) usa Prisma + SQLite local
// (arquivo dev.db) e não está ligada a nenhuma tela do produto — é sobra de um
// scaffold anterior. Não é montada aqui de propósito: SQLite em arquivo não
// funciona em serverless (Vercel), o sistema de arquivos é somente leitura/efêmero.
// Se essa funcionalidade for retomada, precisa migrar para o Supabase (Postgres)
// como todo o resto do app antes de voltar a ser montada.

// ---------- Alertas em tempo real (Server-Sent Events) ----------
// Mantém uma conexão aberta por aba de navegador para empurrar o alerta assim
// que ele é gravado no banco, sem esperar o próximo ciclo de polling do cliente.
// Obs.: em ambiente serverless (Vercel) essa conexão não sobrevive entre invocações;
// nesse caso o polling do cliente (client-side) continua sendo o mecanismo de entrega.
const clientesSSE = new Set();

app.get('/api/eventos', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
  });
  // Em serverless (Vercel) essa conexão não fica de pé entre invocações — o navegador
  // vai cair e tentar de novo. "retry" evita que ele martele o endpoint a cada ~3s
  // (padrão do EventSource); o polling da tela de Alertas já cobre a entrega nesse caso.
  res.write('retry: 30000\n');
  res.write(':ok\n\n');
  if (res.flushHeaders) res.flushHeaders();

  clientesSSE.add(res);
  req.on('close', () => clientesSSE.delete(res));
});

function transmitirAlerta(alerta) {
  const payload = `event: alerta\ndata: ${JSON.stringify(alerta)}\n\n`;
  for (const cliente of clientesSSE) {
    cliente.write(payload);
  }
}

const TIPOS_NOTIFICACAO_ALERTA = new Set(['padrao', 'urgente', 'silencioso']);

// Chamado pelo watchdog local (monitor_bot_infinito.py) quando o bot_infinito.py
// para de rodar (ou volta a rodar) no PC do usuário. Reaproveita o mesmo caminho de
// notificação dos alertas de palavra-chave: pop-up/som em qualquer aba aberta (SSE)
// e mensagem pelo webhook do WhatsApp configurado.
app.post('/api/bot/alerta', async (req, res) => {
  const mensagem = String((req.body || {}).mensagem || '').trim();
  const tipoNotificacaoBruto = String((req.body || {}).tipoNotificacao || 'urgente').trim();
  const tipoNotificacao = TIPOS_NOTIFICACAO_ALERTA.has(tipoNotificacaoBruto) ? tipoNotificacaoBruto : 'urgente';

  if (!mensagem) {
    return res.status(400).json({ erro: 'Informe a mensagem do alerta.' });
  }

  const alerta = {
    id: 'bot-' + Date.now(),
    palavraEncontrada: 'Robô local',
    tipoNotificacao,
    mensagem,
    criadoEm: new Date().toISOString(),
  };

  transmitirAlerta(alerta);

  try {
    const supabase = getSupabase();
    await notificarWhatsapp(supabase, [alerta]);
  } catch (erroWhatsapp) {
    console.error('Erro ao notificar WhatsApp sobre status do robô:', erroWhatsapp.message);
  }

  res.json({ ok: true });
});

app.get('/api/buscar', async (req, res) => {
  const uasg = normalizarUasg(req.query.uasg);
  const pregaoRaw = String(req.query.pregao || '').trim();

  if (!uasg) {
    return res.status(400).json({ erro: 'Informe o código UASG do órgão.' });
  }

  const pregaoFiltro = normalizarNumeroPregao(pregaoRaw);

  try {
    const resultados = [];
    let fimJanela = new Date();

    // A API limita o intervalo de datas a 365 dias, então consultamos em janelas anuais sucessivas.
    for (let janela = 0; janela < JANELAS_DE_1_ANO; janela++) {
      const inicioJanela = new Date(fimJanela);
      inicioJanela.setDate(inicioJanela.getDate() - 365);

      for (let pagina = 1; pagina <= MAX_PAGINAS_POR_JANELA; pagina++) {
        const params = new URLSearchParams({
          pagina: String(pagina),
          tamanhoPagina: String(TAMANHO_PAGINA),
          codigoModalidade: String(MODALIDADE_PREGAO_ELETRONICO),
          unidadeOrgaoCodigoUnidade: uasg,
          dataPublicacaoPncpInicial: formatarData(inicioJanela),
          dataPublicacaoPncpFinal: formatarData(fimJanela),
        });

        const resposta = await fetch(`${PNCP_API}?${params.toString()}`, {
          headers: { Accept: 'application/json' },
        });

        if (!resposta.ok) {
          throw new Error(`API do Compras.gov.br retornou status ${resposta.status}`);
        }

        const dados = await resposta.json();
        resultados.push(...(dados.resultado || []));

        if (pagina >= (dados.totalPaginas || 1)) break;
      }

      fimJanela = inicioJanela;
    }

    const filtrados = pregaoFiltro
      ? resultados.filter((item) => {
          const numeroBate = String(item.numeroCompra || '').replace(/^0+/, '') === pregaoFiltro.numero;
          const anoBate = pregaoFiltro.ano ? item.anoCompraPncp === pregaoFiltro.ano : true;
          return numeroBate && anoBate;
        })
      : resultados;

    const itens = filtrados
      .map((item) => ({
        idCompra: item.idCompra,
        uasg: item.unidadeOrgaoCodigoUnidade,
        unidade: item.unidadeOrgaoNomeUnidade,
        orgao: item.orgaoEntidadeRazaoSocial,
        uf: item.unidadeOrgaoUfSigla,
        municipio: item.unidadeOrgaoMunicipioNome,
        numeroPregao: item.numeroCompra,
        anoPregao: item.anoCompraPncp,
        modalidade: item.modalidadeNome,
        objeto: item.objetoCompra,
        situacao: item.situacaoCompraNomePncp,
        valorEstimado: item.valorTotalEstimado,
        dataAbertura: item.dataAberturaPropostaPncp,
        dataEncerramento: item.dataEncerramentoPropostaPncp,
        link: `https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra=${item.idCompra}`,
        monitorado: false,
      }))
      // Licitacoes revogadas nao interessam para novo monitoramento - fora do resultado da busca.
      .filter((item) => !String(item.situacao || '').toLowerCase().includes('revogad'));

    if (itens.length > 0) {
      try {
        const supabase = getSupabase();
        const { data: jaMonitorados, error } = await supabase
          .from('pregoes_monitorados')
          .select('id_compra')
          .in('id_compra', itens.map((item) => item.idCompra));

        if (error) throw error;

        const monitoradosSet = new Set((jaMonitorados || []).map((row) => row.id_compra));
        itens.forEach((item) => {
          item.monitorado = monitoradosSet.has(item.idCompra);
        });
      } catch (erroSupabase) {
        console.error('Erro ao verificar pregões monitorados no Supabase:', erroSupabase.message);
      }
    }

    res.json({ total: itens.length, itens });
  } catch (erro) {
    console.error('Erro ao consultar API do Compras.gov.br:', erro.message);
    res.status(502).json({
      erro: 'Não foi possível consultar o Compras.gov.br agora. Tente novamente em instantes.',
    });
  }
});

app.get('/api/monitorados', async (req, res) => {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('pregoes_monitorados')
      .select('*')
      .order('favorito', { ascending: false })
      .order('criado_em', { ascending: false });

    if (error) throw error;

    const itens = (data || []).map((row) => ({
      idCompra: row.id_compra,
      uasg: row.uasg,
      unidade: row.unidade,
      orgao: row.orgao,
      uf: row.uf,
      municipio: row.municipio,
      numeroPregao: row.numero_pregao,
      anoPregao: row.ano_pregao,
      modalidade: row.modalidade,
      objeto: row.objeto,
      situacao: row.situacao,
      valorEstimado: row.valor_estimado,
      dataAbertura: row.data_abertura,
      dataEncerramento: row.data_encerramento,
      link: row.link,
      criadoEm: row.criado_em,
      atualizadoEm: row.atualizado_em,
      favorito: row.favorito,
    }));

    res.json({ total: itens.length, itens });
  } catch (erro) {
    console.error('Erro ao carregar monitorados do Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar os pregões monitorados agora.' });
  }
});

app.post('/api/monitorar', async (req, res) => {
  const item = req.body || {};

  if (!item.idCompra) {
    return res.status(400).json({ erro: 'Dados do pregão incompletos (idCompra ausente).' });
  }

  try {
    const supabase = getSupabase();

    const { error } = await supabase.from('pregoes_monitorados').upsert(
      {
        id_compra: item.idCompra,
        uasg: item.uasg,
        unidade: item.unidade,
        orgao: item.orgao,
        uf: item.uf,
        municipio: item.municipio,
        numero_pregao: item.numeroPregao,
        ano_pregao: item.anoPregao,
        modalidade: item.modalidade,
        objeto: item.objeto,
        situacao: item.situacao,
        valor_estimado: item.valorEstimado,
        data_abertura: item.dataAbertura,
        data_encerramento: item.dataEncerramento,
        link: item.link,
        atualizado_em: new Date().toISOString(),
      },
      { onConflict: 'id_compra' }
    );

    if (error) throw error;

    res.json({ ok: true });

    // A chamada do bot python e do worker foi removida pois o Vercel não suporta processos em background.
    // O script bot_infinito.py rodando externamente assumirá este trabalho.

  } catch (erro) {
    console.error('Erro ao salvar no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível salvar no Supabase agora.' });
  }
});

app.get('/api/licitacoes/busca', async (req, res) => {
  const {
    cidade,
    uf,
    dataAberturaInicio,
    dataAberturaFim,
    valorMin,
    valorMax,
    uasg,
    pregao,
    objeto,
    situacao,
    modalidade,
    esfera,
    favorito,
    ordenacao = 'data_abertura',
    direcao = 'desc',
    pagina = 1,
    limite = 10
  } = req.query;

  try {
    const supabase = getSupabase();

    // Buscar lista de favoritos para mapeamento
    const { data: monitored } = await supabase
      .from('pregoes_monitorados')
      .select('id_compra, favorito');
    
    const favMap = {};
    if (monitored) {
      monitored.forEach((m) => {
        favMap[m.id_compra] = m.favorito;
      });
    }

    let query = supabase
      .from('licitacoes_pncp')
      .select('*', { count: 'exact' });

    // Aplicar filtros dinâmicos
    // Cidade não filtra aqui: "ilike" do Postgres não ignora acento/cedilha
    // ("Brasilia" não bateria com "Brasília"), então é filtrada em JS mais abaixo,
    // depois de normalizar os dois lados com removerAcentos().
    if (uf && uf.trim() && uf !== 'TODOS') {
      query = query.eq('uf', uf.trim());
    }
    if (dataAberturaInicio && dataAberturaInicio.trim()) {
      query = query.gte('data_abertura', `${dataAberturaInicio.trim()}T00:00:00Z`);
    }
    if (dataAberturaFim && dataAberturaFim.trim()) {
      query = query.lte('data_abertura', `${dataAberturaFim.trim()}T23:59:59Z`);
    }
    if (valorMin && valorMin.trim()) {
      query = query.gte('valor_estimado', parseFloat(valorMin));
    }
    if (valorMax && valorMax.trim()) {
      query = query.lte('valor_estimado', parseFloat(valorMax));
    }
    if (uasg && uasg.trim()) {
      query = query.ilike('uasg', `%${uasg.trim()}%`);
    }
    if (pregao && pregao.trim()) {
      query = query.ilike('numero_pregao', `%${pregao.trim()}%`);
    }
    if (objeto && objeto.trim()) {
      // Aceita mais de um termo separado por vírgula ou ponto e vírgula (ver campo
      // "Palavra no Objeto" em licitacao.html): basta bater com qualquer um deles.
      const termosObjeto = objeto
        .split(/[;,]/)
        .map((t) => t.trim())
        .filter(Boolean);

      if (termosObjeto.length > 1) {
        query = query.or(termosObjeto.map((t) => `objeto.ilike.%${t}%`).join(','));
      } else if (termosObjeto.length === 1) {
        query = query.ilike('objeto', `%${termosObjeto[0]}%`);
      }
    }
    if (situacao && situacao.trim() && situacao !== 'TODOS') {
      query = query.ilike('situacao', `%${situacao.trim()}%`);
    }
    if (modalidade && modalidade.trim() && modalidade !== 'TODOS') {
      query = query.ilike('modalidade', `%${modalidade.trim()}%`);
    }
    if (esfera && ESFERA_LABELS[esfera.trim()]) {
      query = query.eq('dados_completos->>orgaoEntidadeEsferaId', esfera.trim());
    }
    if (favorito === 'true') {
      const favIds = Object.keys(favMap).filter((id) => favMap[id] === true);
      if (favIds.length === 0) {
        return res.json({
          total: 0,
          pagina: Math.max(1, parseInt(pagina, 10) || 1),
          limite: Math.max(1, parseInt(limite, 10) || 10),
          itens: [],
        });
      }
      query = query.in('id_compra', favIds);
    }

    // Ordenação segura
    const camposOrdenacaoValidos = ['data_abertura', 'valor_estimado', 'uasg', 'criado_em', 'atualizado_em'];
    const campoFinal = camposOrdenacaoValidos.includes(ordenacao) ? ordenacao : 'data_abertura';
    const direcaoAsc = direcao === 'asc';

    query = query.order(campoFinal, { ascending: direcaoAsc });

    const numPagina = Math.max(1, parseInt(pagina, 10) || 1);
    const numLimite = Math.max(1, parseInt(limite, 10) || 10);

    let data;
    let count;

    const cidadeFiltro = cidade && cidade.trim() ? removerAcentos(cidade.trim()) : null;

    if (cidadeFiltro) {
      // Município não dá pra filtrar no Postgres aqui (precisa ignorar acento), então
      // busca um lote maior já ordenado, filtra em JS e pagina manualmente. Um teto de
      // 5000 linhas evita carregar a base toda de uma vez num filtro muito genérico.
      const { data: candidatos, error: erroCandidatos } = await query.limit(5000);
      if (erroCandidatos) throw erroCandidatos;

      const filtrados = (candidatos || []).filter((row) =>
        removerAcentos(row.municipio).includes(cidadeFiltro)
      );

      count = filtrados.length;
      const doItem = (numPagina - 1) * numLimite;
      data = filtrados.slice(doItem, doItem + numLimite);
    } else {
      const doItem = (numPagina - 1) * numLimite;
      const ateItem = doItem + numLimite - 1;
      const resultado = await query.range(doItem, ateItem);
      if (resultado.error) throw resultado.error;
      data = resultado.data;
      count = resultado.count;
    }

    const itens = (data || []).map((row) => ({
      ...mapearLicitacao(row),
      favorito: !!favMap[row.id_compra],
    }));

    res.json({
      total: count || 0,
      pagina: numPagina,
      limite: numLimite,
      itens,
    });
  } catch (erro) {
    console.error('Erro ao buscar licitações no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível buscar as licitações agora.' });
  }
});

// Rota pública (sem login, ver exigirLogin) usada pela página de compartilhamento
// de card: devolve só a licitação pedida, sem busca/listagem, pra não expor a
// base toda a quem não tem conta — só quem já tem o link específico.
app.get('/api/publico/licitacoes/:idCompra', async (req, res) => {
  const { idCompra } = req.params;

  try {
    const supabase = getSupabase();
    const { data: row, error } = await supabase
      .from('licitacoes_pncp')
      .select('*')
      .eq('id_compra', idCompra)
      .maybeSingle();

    if (error) throw error;
    if (!row) {
      return res.status(404).json({ erro: 'Licitação não encontrada.' });
    }

    res.json(mapearLicitacao(row));
  } catch (erro) {
    console.error('Erro ao buscar licitação pública no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar a licitação agora.' });
  }
});

// Resolve o arquivo (edital) da licitação direto na API do PNCP e redireciona pra
// URL de download real, em vez de mandar o usuário pra página de listagem no portal.
app.get('/api/licitacoes/:idCompra/arquivo', async (req, res) => {
  const { idCompra } = req.params;

  try {
    const supabase = getSupabase();
    const { data: row, error } = await supabase
      .from('licitacoes_pncp')
      .select('id_compra, dados_completos')
      .eq('id_compra', idCompra)
      .single();

    if (error || !row) {
      return res.status(404).send('Licitação não encontrada.');
    }

    const info = extrairCnpjAnoSequencial(row.dados_completos, row.id_compra);
    if (!info) {
      return res.status(404).send('Não foi possível localizar os arquivos desta licitação no PNCP.');
    }

    const respostaPncp = await fetch(
      `https://pncp.gov.br/api/pncp/v1/orgaos/${info.cnpj}/compras/${info.ano}/${info.sequencial}/arquivos`,
      { headers: { Accept: 'application/json' } }
    );

    if (!respostaPncp.ok) {
      return res.status(502).send('Não foi possível consultar os arquivos no PNCP agora.');
    }

    const documentos = await respostaPncp.json();
    const primeiroDocumento = Array.isArray(documentos) ? documentos[0] : null;
    const urlArquivo = primeiroDocumento?.uri || primeiroDocumento?.url;

    if (!urlArquivo) {
      return res.status(404).send('Nenhum arquivo disponível para esta licitação no PNCP.');
    }

    res.redirect(urlArquivo);
  } catch (erro) {
    console.error('Erro ao buscar arquivo da licitação no PNCP:', erro.message);
    res.status(502).send('Não foi possível baixar o arquivo agora.');
  }
});

app.patch('/api/monitorados/:idCompra/favorito', async (req, res) => {
  const { idCompra } = req.params;
  const favorito = Boolean((req.body || {}).favorito);

  try {
    const supabase = getSupabase();
    
    // Tenta primeiro atualizar
    const { data: updated, error: updateError } = await supabase
      .from('pregoes_monitorados')
      .update({ favorito, atualizado_em: new Date().toISOString() })
      .eq('id_compra', idCompra)
      .select();

    if (updateError) throw updateError;

    // Se não atualizou nada (não existia no monitoramento), buscamos no cache e inserimos
    if (!updated || updated.length === 0) {
      const { data: cachedItem, error: fetchError } = await supabase
        .from('licitacoes_pncp')
        .select('*')
        .eq('id_compra', idCompra)
        .single();

      if (fetchError || !cachedItem) {
        return res.status(404).json({ erro: 'Licitação não encontrada para favoritar.' });
      }

      const { error: insertError } = await supabase
        .from('pregoes_monitorados')
        .insert({
          id_compra: cachedItem.id_compra,
          uasg: cachedItem.uasg,
          orgao: cachedItem.orgao,
          unidade: cachedItem.unidade,
          numero_pregao: cachedItem.numero_pregao,
          ano_pregao: cachedItem.ano_pregao,
          municipio: cachedItem.municipio,
          uf: cachedItem.uf,
          data_abertura: cachedItem.data_abertura,
          valor_estimado: cachedItem.valor_estimado,
          objeto: cachedItem.objeto,
          situacao: cachedItem.situacao,
          modalidade: cachedItem.modalidade,
          link: cachedItem.link,
          favorito: favorito,
          fase_producao: favorito ? FASE_PRODUCAO_INICIAL : null,
          atualizado_em: new Date().toISOString()
        });

      if (insertError) throw insertError;
    } else if (favorito && !updated[0].fase_producao) {
      // Já existia no monitoramento mas nunca entrou (ou saiu) do quadro de Produção:
      // favoritar de novo já entra automaticamente na primeira fase (Participação).
      const { error: faseError } = await supabase
        .from('pregoes_monitorados')
        .update({ fase_producao: FASE_PRODUCAO_INICIAL })
        .eq('id_compra', idCompra);

      if (faseError) throw faseError;
    }

    res.json({ ok: true, favorito });
  } catch (erro) {
    console.error('Erro ao atualizar favorito no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível atualizar o favorito agora.' });
  }
});

// Quadro de Produção (kanban): licitações favoritadas que entraram no processo de
// participação, agrupadas pela fase atual (ver FASES_PRODUCAO).
app.get('/api/producao', async (req, res) => {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('pregoes_monitorados')
      .select('*')
      .eq('favorito', true)
      .not('fase_producao', 'is', null)
      .order('atualizado_em', { ascending: false });

    if (error) throw error;

    const itens = (data || []).map((row) => ({
      ...mapearLicitacao(row),
      fase: row.fase_producao,
    }));

    res.json({ itens });
  } catch (erro) {
    console.error('Erro ao buscar quadro de produção no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar o quadro de produção agora.' });
  }
});

app.patch('/api/producao/:idCompra/fase', async (req, res) => {
  const { idCompra } = req.params;
  const fase = String((req.body || {}).fase || '').trim();

  if (!FASES_PRODUCAO.includes(fase)) {
    return res.status(400).json({ erro: 'Fase inválida.' });
  }

  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('pregoes_monitorados')
      .update({ fase_producao: fase, atualizado_em: new Date().toISOString() })
      .eq('id_compra', idCompra)
      .eq('favorito', true)
      .select();

    if (error) throw error;
    if (!data || data.length === 0) {
      return res.status(404).json({ erro: 'Licitação não encontrada no quadro de produção.' });
    }

    res.json({ ok: true, fase });
  } catch (erro) {
    console.error('Erro ao atualizar fase de produção no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível atualizar a fase agora.' });
  }
});

// Usado pelo bot (monitor_mensagens.py) quando a pagina do pregao nao abre o chat de
// mensagens e mostra a tela "Informacoes adicionais da compra" - isso indica que a
// licitacao foi revogada/encerrada, entao a situacao e marcada para sair da varredura.
app.patch('/api/monitorados/:idCompra/situacao', async (req, res) => {
  const { idCompra } = req.params;
  const situacao = String((req.body || {}).situacao || '').trim();

  if (!situacao) {
    return res.status(400).json({ erro: 'Informe a situacao.' });
  }

  try {
    const supabase = getSupabase();
    const { error } = await supabase
      .from('pregoes_monitorados')
      .update({ situacao, atualizado_em: new Date().toISOString() })
      .eq('id_compra', idCompra);

    if (error) throw error;

    res.json({ ok: true, situacao });
  } catch (erro) {
    console.error('Erro ao atualizar situacao no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível atualizar a situação agora.' });
  }
});

app.delete('/api/monitorados/:idCompra', async (req, res) => {
  const { idCompra } = req.params;

  try {
    const supabase = getSupabase();
    const { error } = await supabase.from('pregoes_monitorados').delete().eq('id_compra', idCompra);

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao excluir monitorado no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível excluir o pregão agora.' });
  }
});

app.get('/api/mensagens/:idCompra', async (req, res) => {
  const { idCompra } = req.params;

  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('mensagens_chat')
      .select('*')
      .eq('id_compra', idCompra)
      .order('data_hora', { ascending: false, nullsFirst: false });

    if (error) throw error;

    const itens = (data || []).map((row) => ({
      remetente: row.remetente,
      grupo: row.grupo,
      mensagem: row.mensagem,
      dataHoraTexto: row.data_hora_texto,
      dataHora: row.data_hora,
    }));

    res.json({ total: itens.length, itens });
  } catch (erro) {
    console.error('Erro ao carregar mensagens do Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar as mensagens agora.' });
  }
});



app.post('/api/mensagens/:idCompra', async (req, res) => {
  const { idCompra } = req.params;
  const { texto } = req.body || {};

  if (!texto || !texto.trim()) {
    return res.status(400).json({ erro: 'Cole o texto das mensagens antes de salvar.' });
  }

  const mensagens = parseMensagensColadas(texto);

  if (mensagens.length === 0) {
    return res.status(400).json({ erro: 'Não consegui identificar mensagens nesse texto. Confira o formato colado.' });
  }

  try {
    const supabase = getSupabase();

    // Descobre quais dessas mensagens já existiam, para não gerar alerta duplicado ao colar o mesmo texto de novo.
    const { data: existentes, error: erroExistentes } = await supabase
      .from('mensagens_chat')
      .select('remetente, mensagem, data_hora_texto')
      .eq('id_compra', idCompra);

    if (erroExistentes) throw erroExistentes;

    const chave = (m) => `${m.remetente}||${m.mensagem}||${m.data_hora_texto || m.dataHoraTexto}`;
    const jaExistiaSet = new Set((existentes || []).map(chave));

    const linhas = mensagens.map((m) => ({
      id_compra: idCompra,
      remetente: m.remetente,
      grupo: m.grupo,
      mensagem: m.mensagem,
      data_hora_texto: m.dataHoraTexto,
      data_hora: m.dataHora,
    }));

    const { data: salvas, error } = await supabase
      .from('mensagens_chat')
      .upsert(linhas, { onConflict: 'id_compra,remetente,mensagem,data_hora_texto' })
      .select('id, remetente, mensagem, data_hora_texto');

    if (error) throw error;

    // Atualiza o timestamp de monitoracao/atualizacao das mensagens do pregao
    await supabase
      .from('pregoes_monitorados')
      .update({ atualizado_em: new Date().toISOString() })
      .eq('id_compra', idCompra);

    const novas = (salvas || []).filter((m) => !jaExistiaSet.has(chave(m)));
    const alertasGerados = await verificarPalavrasChave(supabase, idCompra, novas);

    // Toda licitação que tiver uma mensagem batendo com palavra-chave monitorada
    // vira favorita automaticamente (evita escrita à toa se já era favorita).
    if (alertasGerados.length > 0) {
      const { error: erroFavorito } = await supabase
        .from('pregoes_monitorados')
        .update({ favorito: true, atualizado_em: new Date().toISOString() })
        .eq('id_compra', idCompra)
        .eq('favorito', false);
      if (erroFavorito) {
        console.error('Erro ao marcar favorito automaticamente:', erroFavorito.message);
      }
    }

    if (alertasGerados.length > 0) {
      try {
        const { data: pregao } = await supabase
          .from('pregoes_monitorados')
          .select('uasg, unidade, orgao, uf, municipio, numero_pregao, ano_pregao, modalidade, objeto, situacao, valor_estimado, data_abertura, data_encerramento, link')
          .eq('id_compra', idCompra)
          .maybeSingle();

        const alertasEnriquecidos = alertasGerados.map((alerta) => ({
          ...alerta,
          uasg: pregao ? pregao.uasg : undefined,
          unidade: pregao ? pregao.unidade : undefined,
          orgao: pregao ? pregao.orgao : undefined,
          uf: pregao ? pregao.uf : undefined,
          municipio: pregao ? pregao.municipio : undefined,
          numeroPregao: pregao ? pregao.numero_pregao : undefined,
          anoPregao: pregao ? pregao.ano_pregao : undefined,
          modalidade: pregao ? pregao.modalidade : undefined,
          objeto: pregao ? pregao.objeto : undefined,
          situacao: pregao ? pregao.situacao : undefined,
          valorEstimado: pregao ? pregao.valor_estimado : undefined,
          dataAbertura: pregao ? pregao.data_abertura : undefined,
          dataEncerramento: pregao ? pregao.data_encerramento : undefined,
          link: pregao ? pregao.link : undefined,
        }));

        alertasEnriquecidos.forEach(transmitirAlerta);

        notificarWhatsapp(supabase, alertasEnriquecidos).catch((erroWhatsapp) => {
          console.error('Erro ao notificar WhatsApp:', erroWhatsapp.message);
        });
      } catch (erroBroadcast) {
        // Notificação em tempo real é um "extra": se falhar, a mensagem já foi salva
        // e o alerta continua acessível pelo polling normal da tela de Alertas.
        console.error('Erro ao transmitir alerta em tempo real:', erroBroadcast.message);
      }
    }

    res.json({ ok: true, total: mensagens.length, novas: novas.length, alertasGerados: alertasGerados.length });
  } catch (erro) {
    console.error('Erro ao salvar mensagens no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível salvar as mensagens agora.', detalhes: erro.message });
  }
});

app.get('/api/palavras', async (req, res) => {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('palavras_monitoradas')
      .select('*')
      .order('criado_em', { ascending: false });

    if (error) throw error;

    res.json({
      itens: (data || []).map((row) => ({
        id: row.id,
        termo: row.termo,
        tipoNotificacao: row.tipo_notificacao || 'padrao',
        criadoEm: row.criado_em,
      })),
    });
  } catch (erro) {
    console.error('Erro ao carregar palavras-chave:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar as palavras-chave agora.' });
  }
});

const TIPOS_NOTIFICACAO_VALIDOS = new Set(['padrao', 'urgente', 'silencioso']);

app.post('/api/palavras', async (req, res) => {
  const termo = String((req.body || {}).termo || '').trim();
  const tipoNotificacaoBruto = String((req.body || {}).tipoNotificacao || 'padrao').trim();
  const tipoNotificacao = TIPOS_NOTIFICACAO_VALIDOS.has(tipoNotificacaoBruto) ? tipoNotificacaoBruto : 'padrao';

  if (!termo) {
    return res.status(400).json({ erro: 'Informe uma palavra-chave.' });
  }

  try {
    const supabase = getSupabase();
    const { error } = await supabase
      .from('palavras_monitoradas')
      .upsert({ termo, tipo_notificacao: tipoNotificacao }, { onConflict: 'termo' });

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao salvar palavra-chave:', erro.message);
    res.status(502).json({ erro: 'Não foi possível salvar a palavra-chave agora.' });
  }
});

app.delete('/api/palavras/:id', async (req, res) => {
  const { id } = req.params;

  try {
    const supabase = getSupabase();
    const { error } = await supabase.from('palavras_monitoradas').delete().eq('id', id);

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao remover palavra-chave:', erro.message);
    res.status(502).json({ erro: 'Não foi possível remover a palavra-chave agora.' });
  }
});

// ---------- WhatsApp (webhook + números) ----------

app.get('/api/whatsapp/config', async (req, res) => {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('whatsapp_config')
      .select('webhook_url')
      .eq('id', 1)
      .maybeSingle();

    if (error) throw error;

    res.json({ webhookUrl: data ? data.webhook_url : null });
  } catch (erro) {
    console.error('Erro ao carregar configuração do WhatsApp:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar a configuração do WhatsApp agora.' });
  }
});

app.post('/api/whatsapp/config', async (req, res) => {
  const webhookUrl = String((req.body || {}).webhookUrl || '').trim();

  if (webhookUrl) {
    try {
      new URL(webhookUrl);
    } catch {
      return res.status(400).json({ erro: 'Informe uma URL de webhook válida.' });
    }
  }

  try {
    const supabase = getSupabase();
    const { error } = await supabase
      .from('whatsapp_config')
      .upsert({ id: 1, webhook_url: webhookUrl || null, atualizado_em: new Date().toISOString() });

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao salvar configuração do WhatsApp:', erro.message);
    res.status(502).json({ erro: 'Não foi possível salvar a configuração do WhatsApp agora.' });
  }
});

app.get('/api/whatsapp/numeros', async (req, res) => {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from('whatsapp_numeros')
      .select('*')
      .order('criado_em', { ascending: false });

    if (error) throw error;

    res.json({
      itens: (data || []).map((row) => ({ id: row.id, numero: row.numero, criadoEm: row.criado_em })),
    });
  } catch (erro) {
    console.error('Erro ao carregar números do WhatsApp:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar os números agora.' });
  }
});

app.post('/api/whatsapp/numeros', async (req, res) => {
  const numeroBruto = String((req.body || {}).numero || '').trim();
  const numero = numeroBruto.replace(/[^\d+]/g, '');

  if (!numero || numero.replace(/\D/g, '').length < 8) {
    return res.status(400).json({ erro: 'Informe um número de telefone válido (com DDD).' });
  }

  try {
    const supabase = getSupabase();
    const { error } = await supabase.from('whatsapp_numeros').upsert({ numero }, { onConflict: 'numero' });

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao salvar número do WhatsApp:', erro.message);
    res.status(502).json({ erro: 'Não foi possível salvar o número agora.' });
  }
});

app.post('/api/whatsapp/testar', async (req, res) => {
  try {
    const supabase = getSupabase();
    const resultado = await testarWebhook(supabase);

    if (resultado.erro) {
      return res.status(400).json({ erro: resultado.erro });
    }

    res.json(resultado);
  } catch (erro) {
    console.error('Erro ao testar webhook do WhatsApp:', erro.message);
    res.status(502).json({ erro: 'Não foi possível testar o webhook agora.' });
  }
});

app.delete('/api/whatsapp/numeros/:id', async (req, res) => {
  const { id } = req.params;

  try {
    const supabase = getSupabase();
    const { error } = await supabase.from('whatsapp_numeros').delete().eq('id', id);

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao remover número do WhatsApp:', erro.message);
    res.status(502).json({ erro: 'Não foi possível remover o número agora.' });
  }
});

app.get('/api/alertas', async (req, res) => {
  const apenasNaoLidos = req.query.apenasNaoLidos === 'true';

  try {
    const supabase = getSupabase();

    let query = supabase.from('alertas_gerados').select('*').order('criado_em', { ascending: false });
    if (apenasNaoLidos) query = query.eq('lido', false);

    const { data: alertas, error } = await query;
    if (error) throw error;

    if (!alertas || alertas.length === 0) {
      return res.json({ total: 0, itens: [] });
    }

    const idsCompra = [...new Set(alertas.map((a) => a.id_compra))];
    const idsMensagem = [...new Set(alertas.map((a) => a.mensagem_id).filter(Boolean))];

    const [{ data: pregoes }, { data: mensagens }] = await Promise.all([
      supabase.from('pregoes_monitorados').select('id_compra, uasg, numero_pregao, ano_pregao, orgao, unidade, link').in('id_compra', idsCompra),
      idsMensagem.length > 0
        ? supabase.from('mensagens_chat').select('id, remetente, mensagem, data_hora_texto').in('id', idsMensagem)
        : Promise.resolve({ data: [] }),
    ]);

    const pregaoPorId = Object.fromEntries((pregoes || []).map((p) => [p.id_compra, p]));
    const mensagemPorId = Object.fromEntries((mensagens || []).map((m) => [m.id, m]));

    const itens = alertas.map((a) => {
      const pregao = pregaoPorId[a.id_compra] || {};
      const mensagem = mensagemPorId[a.mensagem_id] || {};
      return {
        id: a.id,
        idCompra: a.id_compra,
        uasg: pregao.uasg,
        numeroPregao: pregao.numero_pregao,
        anoPregao: pregao.ano_pregao,
        orgao: pregao.orgao,
        unidade: pregao.unidade,
        link: pregao.link,
        palavraEncontrada: a.palavra_encontrada,
        tipoNotificacao: a.tipo_notificacao || 'padrao',
        mensagem: mensagem.mensagem,
        remetente: mensagem.remetente,
        dataHoraTexto: mensagem.data_hora_texto,
        lido: a.lido,
        criadoEm: a.criado_em,
      };
    });

    res.json({ total: itens.length, itens });
  } catch (erro) {
    console.error('Erro ao carregar alertas:', erro.message);
    res.status(502).json({ erro: 'Não foi possível carregar os alertas agora.' });
  }
});

app.post('/api/alertas/:id/marcar-lido', async (req, res) => {
  const { id } = req.params;

  try {
    const supabase = getSupabase();
    const { error } = await supabase.from('alertas_gerados').update({ lido: true }).eq('id', id);

    if (error) throw error;

    res.json({ ok: true });
  } catch (erro) {
    console.error('Erro ao marcar alerta como lido:', erro.message);
    res.status(502).json({ erro: 'Não foi possível atualizar o alerta agora.' });
  }
});

app.get('/api/robo/status', (req, res) => {
  res.json(roboLocal.statusRobo());
});

app.post('/api/robo/iniciar', (req, res) => {
  const resultado = roboLocal.iniciarRobo();
  if (!resultado.ok) return res.status(409).json(resultado);
  res.json(resultado);
});

app.post('/api/robo/parar', (req, res) => {
  const resultado = roboLocal.pararRobo();
  if (!resultado.ok) return res.status(409).json(resultado);
  res.json(resultado);
});

app.get('/api/robo/log', (req, res) => {
  res.json({ linhas: roboLocal.obterLog() });
});

// ---------- Automação de busca de licitações no PNCP ----------
const { fetchPNCPBids } = require('./src/services/pncpFetcher');

// Executa a cada 8 horas (3 vezes ao dia)
const INTERVALO_BUSCA_PNCP = 8 * 60 * 60 * 1000; 
setInterval(() => {
  fetchPNCPBids(2).catch((err) => console.error('[Automação PNCP] Erro na busca em segundo plano:', err.message));
}, INTERVALO_BUSCA_PNCP);

app.listen(PORT, () => {
  console.log(`Servidor rodando na porta ${PORT}`);
  
  // Executa uma busca inicial na inicialização do servidor (últimos 3 dias)
  fetchPNCPBids(3).catch((err) => console.error('[Automação PNCP] Erro na busca inicial:', err.message));
});

module.exports = app;
