require('dotenv/config');
const express = require('express');
const cookieSession = require('cookie-session');
const bcrypt = require('bcryptjs');
const path = require('path');
const { getSupabase } = require('./src/supabaseClient');

const app = express();
const PORT = process.env.PORT || 3001;

const ROTAS_PUBLICAS = new Set(['/login.html', '/api/login', '/style.css']);

function exigirLogin(req, res, next) {
  if (ROTAS_PUBLICAS.has(req.path)) return next();
  
  // Permite que o robô (Python/JS) envie mensagens e consulte a lista sem precisar de sessão
  if (req.path.startsWith('/api/mensagens/') && req.method === 'POST') return next();
  if (req.path === '/api/monitorados' && req.method === 'GET') return next();

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
const { notificarWhatsapp } = require('./src/services/whatsappWebhook');
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

app.get('/api/buscar', async (req, res) => {
  const uasg = String(req.query.uasg || '').trim();
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

    const itens = filtrados.map((item) => ({
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
    }));

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

app.patch('/api/monitorados/:idCompra/favorito', async (req, res) => {
  const { idCompra } = req.params;
  const favorito = Boolean((req.body || {}).favorito);

  try {
    const supabase = getSupabase();
    const { error } = await supabase
      .from('pregoes_monitorados')
      .update({ favorito, atualizado_em: new Date().toISOString() })
      .eq('id_compra', idCompra);

    if (error) throw error;

    res.json({ ok: true, favorito });
  } catch (erro) {
    console.error('Erro ao atualizar favorito no Supabase:', erro.message);
    res.status(502).json({ erro: 'Não foi possível atualizar o favorito agora.' });
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

// O worker de background não funciona em Vercel
// const { startWorker } = require('./worker');

app.listen(PORT, () => {
  console.log(`Servidor rodando na porta ${PORT}`);
  // startWorker(); // Removido para compatibilidade Vercel
});

module.exports = app;
