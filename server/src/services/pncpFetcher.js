const { getSupabase } = require('../supabaseClient');

const PNCP_API = 'https://dadosabertos.compras.gov.br/modulo-contratacoes/1_consultarContratacoes_PNCP_14133';
const TAMANHO_PAGINA = 500;
const MODALIDADE_PREGAO_ELETRONICO = 5;

async function fetchPNCPBids(daysBack = 2) {
  console.log(`[PNCP Fetcher] Iniciando busca de licitações lançadas nos últimos ${daysBack} dias...`);
  
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - daysBack);
  
  const startDateStr = start.toISOString().slice(0, 10);
  const endDateStr = end.toISOString().slice(0, 10);
  
  console.log(`[PNCP Fetcher] Período de busca: de ${startDateStr} até ${endDateStr}`);
  
  let pagina = 1;
  let totalSalvas = 0;
  let temMais = true;
  const supabase = getSupabase();

  try {
    while (temMais) {
      const params = new URLSearchParams({
        pagina: String(pagina),
        tamanhoPagina: String(TAMANHO_PAGINA),
        codigoModalidade: String(MODALIDADE_PREGAO_ELETRONICO),
        dataPublicacaoPncpInicial: startDateStr,
        dataPublicacaoPncpFinal: endDateStr,
      });

      console.log(`[PNCP Fetcher] Consultando página ${pagina}...`);
      
      const resposta = await fetch(`${PNCP_API}?${params.toString()}`, {
        headers: { Accept: 'application/json' },
      });

      if (!resposta.ok) {
        throw new Error(`API do PNCP retornou status ${resposta.status}`);
      }

      const dados = await resposta.json();
      const resultados = dados.resultado || [];
      
      if (resultados.length === 0) {
        console.log('[PNCP Fetcher] Nenhuma licitação encontrada nesta página.');
        break;
      }

      console.log(`[PNCP Fetcher] Página ${pagina} retornou ${resultados.length} registros. Mapeando e salvando...`);

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

      // Filtra duplicados do mesmo lote de dados para evitar erro do Postgres:
      // "ON CONFLICT DO UPDATE command cannot affect row a second time"
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

      totalSalvas += uniqueBatch.length;
      console.log(`[PNCP Fetcher] ${uniqueBatch.length} licitações únicas salvas/atualizadas com sucesso.`);

      const totalPaginas = dados.totalPaginas || 1;
      if (pagina >= totalPaginas) {
        temMais = false;
      } else {
        pagina++;
      }
    }

    console.log(`[PNCP Fetcher] Concluído! Total de licitações armazenadas nesta execução: ${totalSalvas}`);
    return { ok: true, total: totalSalvas };
  } catch (erro) {
    console.error('[PNCP Fetcher] Erro crítico ao buscar licitações no PNCP:', erro.message);
    return { ok: false, erro: erro.message };
  }
}

module.exports = { fetchPNCPBids };

if (require.main === module) {
  // Execução direta via CLI (Batch/Scheduler)
  fetchPNCPBids(3)
    .then((res) => {
      if (res.ok) {
        console.log(`[CLI Exec] Concluído com sucesso. Total: ${res.total}`);
        process.exit(0);
      } else {
        console.error(`[CLI Exec] Concluído com erro: ${res.erro}`);
        process.exit(1);
      }
    })
    .catch((err) => {
      console.error('[CLI Exec] Erro não tratado:', err);
      process.exit(1);
    });
}
