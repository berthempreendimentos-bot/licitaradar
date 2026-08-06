require('dotenv/config');
const { getSupabase } = require('./src/supabaseClient');

async function testDirect() {
  console.log("=== TESTANDO CONEXÃO WEBHOOK DIRETAMENTE ===");
  try {
    const supabase = getSupabase();
    const { data: config, error: errConfig } = await supabase
      .from('whatsapp_config')
      .select('webhook_url')
      .eq('id', 1)
      .maybeSingle();

    if (errConfig) throw errConfig;

    const webhookUrl = config && config.webhook_url;
    console.log("URL do Webhook configurada:", webhookUrl);
    if (!webhookUrl) {
      console.log("⚠️ URL do webhook não configurada no Supabase.");
      return;
    }

    const { data: numerosRows, error: errNums } = await supabase.from('whatsapp_numeros').select('numero');
    if (errNums) throw errNums;

    const numeros = (numerosRows && numerosRows.length > 0)
      ? numerosRows.map((n) => n.numero)
      : ['+5511999999999'];
    console.log("Números para envio:", numeros);

    const mockAlerta = {
      id: 0,
      palavraEncontrada: 'TESTE_DIRETO',
      tipoNotificacao: 'urgente',
      criadoEm: new Date().toISOString(),
      mensagem: 'Esta é uma mensagem de teste do script de validação de comunicação.',
      remetente: 'SISTEMA (SCRIPT)',
      dataHoraTexto: new Date().toLocaleTimeString('pt-BR'),
      idCompra: 'teste-script',
      uasg: '999999',
      unidade: 'Unidade de Teste',
      orgao: 'Órgão de Teste PEPACORP',
      uf: 'DF',
      municipio: 'Brasília',
      numeroPregao: '99999',
      anoPregao: 2026,
      modalidade: 'Pregão Eletrônico',
      objeto: 'Validação da integração do webhook.',
      situacao: 'Divulgação',
      valorEstimado: 50000.0,
      dataAbertura: new Date().toISOString(),
      dataEncerramento: new Date().toISOString(),
      link: 'https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra=teste-script'
    };

    const payload = {
      numeros,
      alertas: [mockAlerta]
    };

    console.log("Enviando requisição POST de teste para google.com...");
    const resposta = await fetch("https://www.google.com");
    console.log(`Resposta do Google (Status ${resposta.status})`);
    console.log("=== FIM DO TESTE ===");
  } catch (err) {
    console.error("❌ Ocorreu um erro no teste:", err.message);
  }
}

testDirect();
