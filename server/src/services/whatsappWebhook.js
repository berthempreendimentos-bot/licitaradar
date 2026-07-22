// Dispara os alertas gerados para um webhook externo (configurado pela tela WhatsApp),
// junto com a lista de números cadastrados — quem recebe e envia a mensagem de fato
// pro WhatsApp é a automação do outro lado do webhook (n8n, Make, Zapier, endpoint próprio etc.).

function mapearAlertaParaPayload(a) {
  return {
    // Alerta / palavra-chave
    id: a.id,
    palavraEncontrada: a.palavraEncontrada,
    tipoNotificacao: a.tipoNotificacao,
    criadoEm: a.criadoEm,
    // Mensagem que disparou o alerta
    mensagem: a.mensagem,
    remetente: a.remetente,
    dataHoraTexto: a.dataHoraTexto,
    // Licitação/pregão
    idCompra: a.idCompra,
    uasg: a.uasg,
    unidade: a.unidade,
    orgao: a.orgao,
    uf: a.uf,
    municipio: a.municipio,
    numeroPregao: a.numeroPregao,
    anoPregao: a.anoPregao,
    modalidade: a.modalidade,
    objeto: a.objeto,
    situacao: a.situacao,
    valorEstimado: a.valorEstimado,
    dataAbertura: a.dataAbertura,
    dataEncerramento: a.dataEncerramento,
    link: a.link,
  };
}

async function buscarConfigWhatsapp(supabase) {
  const { data: config } = await supabase
    .from('whatsapp_config')
    .select('webhook_url')
    .eq('id', 1)
    .maybeSingle();

  const { data: numerosRows } = await supabase.from('whatsapp_numeros').select('numero');

  return {
    webhookUrl: config && config.webhook_url,
    numeros: (numerosRows || []).map((n) => n.numero),
  };
}

async function notificarWhatsapp(supabase, alertas) {
  if (!alertas || alertas.length === 0) return;

  const { webhookUrl, numeros } = await buscarConfigWhatsapp(supabase);
  if (!webhookUrl || numeros.length === 0) return;

  const payload = { numeros, alertas: alertas.map(mapearAlertaParaPayload) };

  try {
    const resposta = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resposta.ok) {
      console.error(`Webhook do WhatsApp retornou status ${resposta.status}`);
    }
  } catch (erro) {
    console.error('Erro ao chamar webhook do WhatsApp:', erro.message);
  }
}

// Usado pelo botão "Testar" da tela de WhatsApp: manda uma mensagem sintética real
// pro webhook configurado e devolve o resultado (em vez de só logar e seguir em frente
// como o notificarWhatsapp faz pros alertas de verdade), pra quem clicou saber na hora
// se o webhook está funcionando ou não.
async function testarWebhook(supabase) {
  const { webhookUrl, numeros } = await buscarConfigWhatsapp(supabase);

  if (!webhookUrl) {
    return { erro: 'Configure e salve a URL do webhook antes de testar.' };
  }
  if (numeros.length === 0) {
    return { erro: 'Cadastre pelo menos um número antes de testar.' };
  }

  const alertaTeste = mapearAlertaParaPayload({
    id: 'teste-' + Date.now(),
    palavraEncontrada: 'teste',
    tipoNotificacao: 'padrao',
    criadoEm: new Date().toISOString(),
    mensagem: 'Esta é uma mensagem de teste do PEPACORP LICITA. Se você recebeu isso, o webhook está funcionando!',
    remetente: 'Sistema',
  });

  const payload = { numeros, alertas: [alertaTeste] };

  let resposta;
  try {
    resposta = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (erroConexao) {
    return { erro: `Não foi possível conectar ao webhook: ${erroConexao.message}` };
  }

  if (!resposta.ok) {
    return { erro: `O webhook respondeu com erro (status ${resposta.status}).` };
  }

  return { ok: true, status: resposta.status, totalNumeros: numeros.length };
}

module.exports = { notificarWhatsapp, testarWebhook };
