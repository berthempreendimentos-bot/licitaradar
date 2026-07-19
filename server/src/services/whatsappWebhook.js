// Dispara os alertas gerados para um webhook externo (configurado pela tela WhatsApp),
// junto com a lista de números cadastrados — quem recebe e envia a mensagem de fato
// pro WhatsApp é a automação do outro lado do webhook (n8n, Make, Zapier, endpoint próprio etc.).
async function notificarWhatsapp(supabase, alertas) {
  if (!alertas || alertas.length === 0) return;

  const { data: config } = await supabase
    .from('whatsapp_config')
    .select('webhook_url')
    .eq('id', 1)
    .maybeSingle();

  const webhookUrl = config && config.webhook_url;
  if (!webhookUrl) return;

  const { data: numerosRows } = await supabase.from('whatsapp_numeros').select('numero');
  const numeros = (numerosRows || []).map((n) => n.numero);
  if (numeros.length === 0) return;

  const payload = {
    numeros,
    alertas: alertas.map((a) => ({
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
    })),
  };

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

module.exports = { notificarWhatsapp };
