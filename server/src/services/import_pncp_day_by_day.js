const { getSupabase } = require('../supabaseClient');

const PNCP_API = 'https://dadosabertos.compras.gov.br/modulo-contratacoes/1_consultarContratacoes_PNCP_14133';
const TAMANHO_PAGINA = 500;
const MODALIDADE_PREGAO_ELETRONICO = 5;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function importDayByDay(startStr = '2026-07-01', endStr) {
  const supabase = getSupabase();
  const start = new Date(startStr + 'T12:00:00');
  const end = endStr ? new Date(endStr + 'T12:00:00') : new Date();
  
  console.log(`[PNCP Histórico] Iniciando importação diária em blocos de 2 dias de ${startStr} até ${end.toISOString().slice(0, 10)}...`);
  
  let current = new Date(start);
  let totalGeral = 0;
  
  while (current <= end) {
    // Definimos o início do bloco (dia atual do loop)
    const startDateStr = current.toISOString().slice(0, 10);
    
    // O final do bloco será o dia seguinte
    const nextDay = new Date(current);
    nextDay.setDate(nextDay.getDate() + 1);
    const endDateStr = nextDay.toISOString().slice(0, 10);
    
    console.log(`\n================== PROCESSANDO INTERVALO: ${startDateStr} até ${endDateStr} ==================`);
    
    let pagina = 1;
    let totalBloco = 0;
    let temMais = true;
    
    try {
      while (temMais) {
        const params = new URLSearchParams({
          pagina: String(pagina),
          tamanhoPagina: String(TAMANHO_PAGINA),
          codigoModalidade: String(MODALIDADE_PREGAO_ELETRONICO),
          dataPublicacaoPncpInicial: startDateStr,
          dataPublicacaoPncpFinal: endDateStr,
        });
        
        console.log(`[PNCP Histórico - ${startDateStr}] Consultando página ${pagina}...`);
        
        const resposta = await fetch(`${PNCP_API}?${params.toString()}`, {
          headers: { Accept: 'application/json' },
        });
        
        if (!resposta.ok) {
          throw new Error(`API do PNCP retornou status ${resposta.status} no intervalo ${startDateStr}-${endDateStr}, página ${pagina}`);
        }
        
        const dados = await resposta.json();
        const resultados = dados.resultado || [];
        
        if (resultados.length === 0) {
          console.log(`[PNCP Histórico - ${startDateStr}] Nenhuma licitação encontrada na página ${pagina}.`);
          break;
        }
        
        const batch = resultados.map((item) => ({
          id_compra: item.idCompra,
          uasg: item.unidadeOrgaoCodigoUnidade,
          unidade: item.unidadeOrgaoNomeUnidade,
          orgao: item.orgaoEntidadeRazaoSocial,
          uf: item.unidadeOrgaoUfSigla,
          municipio: item.unidadeOrgaoMunicipioNome,
          numero_pregao: item.numeroCompra,
          ano_pregao: item.anoCompraPncp,
          modalidade: item.modalidadeNome,
          objeto: item.objetoCompra,
          situacao: item.situacaoCompraNomePncp,
          valor_estimado: item.valorTotalEstimado,
          data_abertura: item.dataAberturaPropostaPncp,
          data_encerramento: item.dataEncerramentoPropostaPncp,
          link: `https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra=${item.idCompra}`,
          dados_completos: item,
          atualizado_em: new Date().toISOString()
        }));
        
        const uniqueBatch = [];
        const seenIds = new Set();
        for (const item of batch) {
          if (item.id_compra && !seenIds.has(item.id_compra)) {
            seenIds.add(item.id_compra);
            uniqueBatch.push(item);
          }
        }
        
        const { error } = await supabase
          .from('licitacoes_pncp')
          .upsert(uniqueBatch, { onConflict: 'id_compra' });
          
        if (error) {
          throw error;
        }
        
        totalBloco += uniqueBatch.length;
        console.log(`[PNCP Histórico - ${startDateStr}] Página ${pagina} salva: ${uniqueBatch.length} registros únicos.`);
        
        const totalPaginas = dados.totalPaginas || 1;
        if (pagina >= totalPaginas) {
          temMais = false;
        } else {
          pagina++;
        }
        
        await sleep(150);
      }
      
      console.log(`[PNCP Histórico - ${startDateStr}] FINALIZADO. Total do bloco: ${totalBloco} licitações.`);
      totalGeral += totalBloco;
      
    } catch (erro) {
      console.error(`[PNCP Histórico - ${startDateStr}] ERRO no intervalo:`, erro.message);
      await sleep(2000);
    }
    
    // Incrementa 2 dias para ir para o próximo bloco de 2 dias não-sobrepostos
    current.setDate(current.getDate() + 2);
    
    await sleep(250);
  }
  
  console.log(`\n==================================================================`);
  console.log(`[PNCP Histórico] IMPORTAÇÃO DIÁRIA CONCLUÍDA!`);
  console.log(`Total geral de licitações salvas/atualizadas: ${totalGeral}`);
  console.log(`==================================================================`);
  return { ok: true, total: totalGeral };
}

if (require.main === module) {
  const hojeStr = new Date().toISOString().slice(0, 10);
  importDayByDay('2026-07-01', hojeStr)
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('Erro na execução do script:', err);
      process.exit(1);
    });
}

module.exports = { importDayByDay };
