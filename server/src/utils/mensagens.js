// Linhas de interface que às vezes vêm junto quando se seleciona o painel inteiro
// (cabeçalhos, filtros, botões, contadores de abas etc.) — não são mensagens.
const LINHAS_RUIDO = [
  /^chat\s*\/\s*mensagens$/i,
  /^visualize aqui as mensagens/i,
  /^filtrar por item monitorado$/i,
  /^todos os itens monitorados$/i,
  /^mover todas as mensagens$/i,
  /^mover mensagens selecionadas$/i,
  /^n[ãa]o lidas/i,
  /^lidas\s*-?\s*\d*$/i,
  /^anota[çc][õo]es\s*-?\s*\d*$/i,
  /^origem$/i,
  /^item\s*\/\s*lote$/i,
  /^mensagem$/i,
  /^hora$/i,
  /^lido por$/i,
  /^lido em$/i,
  /^preg[ãa]o eletr[ôo]nico n[°ºo]/i,
  /^\d+$/, // contadores soltos (ex.: "118")
];

function ehLinhaDeRuido(linha) {
  return LINHAS_RUIDO.some((re) => re.test(linha));
}

// Extrai mensagens do texto colado pelo usuário (copiado do painel "Mensagens" do ComprasNet).
// Cada mensagem segue o padrão: remetente [+ "Grupo N" opcional] / texto / data e hora.
// Tolera ruído de interface misturado no texto e pequenas variações de quebra de linha.
function parseMensagensColadas(texto) {
  const linhasLimpas = String(texto || '')
    .replace(/\r\n/g, '\n')
    .replace(/ /g, ' ') // replace non-breaking space
    .split('\n')
    .map((l) => l.trim().replace(/\s+/g, ' '))
    .filter((l) => l && !ehLinhaDeRuido(l));

  const textoLimpo = linhasLimpas.join('\n');

  const blocos = textoLimpo
    .split(/\n(?=\s*Mensagem d[oa]\b)/i)
    .map((b) => b.trim())
    .filter((b) => /^\s*Mensagem d[oa]\b/i.test(b)); // Garante que é realmente um bloco de mensagem e não lixo do cabeçalho

  return blocos
    .map((bloco) => {
      const linhas = bloco.split('\n').map((l) => l.trim()).filter(Boolean);
      if (linhas.length < 2) return null;

      // O "Grupo N" pode vir na mesma linha do remetente ou numa linha própria logo em seguida.
      let remetente = linhas[0];
      let grupo = null;
      let inicioMensagem = 1;

      const grupoNaPrimeiraLinha = remetente.match(/Grupo\s*\d+/i);
      if (grupoNaPrimeiraLinha) {
        grupo = grupoNaPrimeiraLinha[0];
        remetente = remetente.replace(/Grupo\s*\d+/i, '').trim();
      } else if (linhas[1] && /^Grupo\s*\d+$/i.test(linhas[1])) {
        grupo = linhas[1];
        inicioMensagem = 2;
      }

      // Procura a data/hora a partir do fim do bloco, caso sobre alguma linha de ruído depois dela.
      let indiceData = -1;
      let dataMatch = null;
      for (let i = linhas.length - 1; i >= inicioMensagem; i--) {
        const m = linhas[i].match(/(\d{2}\/\d{2}\/\d{4})\s+(\d{2}:\d{2})/);
        if (m) {
          indiceData = i;
          dataMatch = m;
          break;
        }
      }

      const dataHoraTexto = dataMatch ? dataMatch[0] : null;
      const linhasMensagem = indiceData >= 0
        ? linhas.slice(inicioMensagem, indiceData)
        : linhas.slice(inicioMensagem);
      const mensagem = linhasMensagem.join(' ').replace(/\s+/g, ' ').trim();

      let dataHora = null;
      if (dataMatch) {
        const [, data, hora] = dataMatch;
        const [dia, mes, ano] = data.split('/');
        dataHora = `${ano}-${mes}-${dia}T${hora}:00-03:00`;
      }

      if (!mensagem) return null;

      return { remetente, grupo, mensagem, dataHoraTexto, dataHora };
    })
    .filter(Boolean);
}

// Verifica as mensagens recém-salvas contra as palavras-chave cadastradas e
// registra um alerta em alertas_gerados para cada combinação mensagem+palavra encontrada.
// Retorna os alertas inseridos (já com o texto da mensagem) para permitir notificação imediata.
async function verificarPalavrasChave(supabase, idCompra, mensagensComId) {
  const { data: palavras, error: erroPalavras } = await supabase
    .from('palavras_monitoradas')
    .select('termo, tipo_notificacao');

  if (erroPalavras) throw erroPalavras;
  if (!palavras || palavras.length === 0) return [];

  const mensagemPorId = new Map(mensagensComId.map((m) => [m.id, m]));

  const alertas = [];
  for (const msg of mensagensComId) {
    const textoBusca = msg.mensagem.toLowerCase();
    for (const { termo, tipo_notificacao: tipoNotificacao } of palavras) {
      if (textoBusca.includes(termo.toLowerCase())) {
        alertas.push({
          id_compra: idCompra,
          mensagem_id: msg.id,
          palavra_encontrada: termo,
          tipo_notificacao: tipoNotificacao || 'padrao',
        });
      }
    }
  }

  if (alertas.length === 0) return [];

  const { data: inseridos, error: erroInsert } = await supabase
    .from('alertas_gerados')
    .insert(alertas)
    .select('id, id_compra, mensagem_id, palavra_encontrada, tipo_notificacao, criado_em');
  if (erroInsert) throw erroInsert;

  return (inseridos || []).map((alerta) => {
    const msg = mensagemPorId.get(alerta.mensagem_id);
    return {
      id: alerta.id,
      idCompra: alerta.id_compra,
      palavraEncontrada: alerta.palavra_encontrada,
      tipoNotificacao: alerta.tipo_notificacao,
      mensagem: msg ? msg.mensagem : null,
      remetente: msg ? msg.remetente : null,
      dataHoraTexto: msg ? msg.data_hora_texto : null,
      criadoEm: alerta.criado_em,
    };
  });
}

module.exports = {
  parseMensagensColadas,
  verificarPalavrasChave
};
