require('dotenv/config');
const puppeteer = require('puppeteer');
const { getSupabase } = require('./src/supabaseClient');
const { parseMensagensColadas, verificarPalavrasChave } = require('./src/utils/mensagens');

const INTERVAL_MINUTES = 5;
const PNCP_API = 'https://dadosabertos.compras.gov.br/modulo-contratacoes/1_consultarContratacoes_PNCP_14133';

async function updateBidStatus(supabase, bid) {
  try {
    const end = new Date();
    const start = new Date();
    start.setFullYear(start.getFullYear() - 2); // check last 2 years

    const params = new URLSearchParams({
      pagina: '1',
      tamanhoPagina: '500',
      codigoModalidade: '5',
      unidadeOrgaoCodigoUnidade: bid.uasg,
      dataPublicacaoPncpInicial: start.toISOString().slice(0, 10),
      dataPublicacaoPncpFinal: end.toISOString().slice(0, 10),
    });

    const response = await fetch(`${PNCP_API}?${params.toString()}`, {
      headers: { Accept: 'application/json' },
    });

    if (response.ok) {
      const data = await response.json();
      const items = data.resultado || [];
      const match = items.find(i => String(i.idCompra) === String(bid.id_compra));
      
      if (match && match.situacaoCompraNomePncp !== bid.situacao) {
        console.log(`[Worker] Atualizando situação do pregão ${bid.numero_pregao} para ${match.situacaoCompraNomePncp}`);
        await supabase.from('pregoes_monitorados').update({
          situacao: match.situacaoCompraNomePncp,
          atualizado_em: new Date().toISOString()
        }).eq('id_compra', bid.id_compra);
      }
    }
  } catch (err) {
    console.error(`[Worker] Erro ao atualizar status do pregão ${bid.id_compra}:`, err.message);
  }
}

async function runWorkerCycle() {
  console.log(`\n[Worker] Iniciando ciclo de verificação automática... (${new Date().toISOString()})`);
  const supabase = getSupabase();

  const { data: bids, error } = await supabase.from('pregoes_monitorados').select('*');
  
  if (error) {
    console.error('[Worker] Erro ao carregar pregões monitorados:', error.message);
    return;
  }

  if (!bids || bids.length === 0) {
    console.log('[Worker] Nenhum pregão monitorado no momento.');
    return;
  }

  console.log(`[Worker] Encontrados ${bids.length} pregões monitorados.`);

  try {
    for (const bid of bids) {
      await updateBidStatus(supabase, bid);
    }
  } finally {
    console.log(`[Worker] Ciclo de verificação concluído.`);
  }
}

// Inicializa o worker
function startWorker() {
  console.log(`[Worker] Inicializado. Rodando a cada ${INTERVAL_MINUTES} minutos.`);
  runWorkerCycle(); // Rodar a primeira vez imediatamente
  setInterval(runWorkerCycle, INTERVAL_MINUTES * 60 * 1000);
}

async function runWorkerForSingleBid(bid) {
  console.log(`\n[Worker] Iniciando verificação pontual para o pregão ${bid.numero_pregao}... (${new Date().toISOString()})`);
  const supabase = getSupabase();

  try {
    await updateBidStatus(supabase, bid);
  } finally {
    console.log(`[Worker] Verificação pontual concluída para ${bid.numero_pregao}.`);
  }
}

module.exports = { startWorker, runWorkerCycle, runWorkerForSingleBid };

if (require.main === module) {
  // If run directly
  startWorker();
}
