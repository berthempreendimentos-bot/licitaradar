// notificacoes.js — som + pop-up de alerta em tempo real, compartilhado entre as páginas.
// Conecta via Server-Sent Events (/api/eventos) e dispara a notificação assim que o
// servidor grava um alerta no banco, sem esperar o próximo ciclo de polling da tela.
(function () {
  const NOTIF_PREF_KEY = 'radar-notificar-computador';
  const ESTILO_PREF_KEY = 'radar-estilo-alarme';
  let notificacaoPermitida = 'Notification' in window && Notification.permission === 'granted';

  function preferenciaAtiva() {
    const salvo = localStorage.getItem(NOTIF_PREF_KEY);
    return salvo === null ? true : salvo === 'true';
  }

  function definirPreferencia(ativo) {
    localStorage.setItem(NOTIF_PREF_KEY, ativo ? 'true' : 'false');
  }

  function pedirPermissao(avisar) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      notificacaoPermitida = true;
      return;
    }
    if (Notification.permission === 'denied') {
      if (avisar) avisar('Notificações bloqueadas pelo navegador. Habilite nas configurações do site para receber pop-ups.');
      return;
    }
    Notification.requestPermission().then((perm) => {
      notificacaoPermitida = perm === 'granted';
      if (perm !== 'granted' && avisar) {
        avisar('Permissão de notificação negada pelo navegador. Habilite nas configurações do site para receber pop-ups.');
      }
    });
  }

  if (preferenciaAtiva()) pedirPermissao();

  // ---------- Sons dos alarmes (Web Audio API, sem arquivo externo) ----------
  let audioCtx = null;
  function getAudioCtx() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return audioCtx;
  }
  // Navegadores exigem uma interação do usuário antes de liberar áudio.
  document.addEventListener('click', () => { getAudioCtx().resume(); }, { once: true });

  function bipe(ctx, frequencia, inicio, duracao, volume) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.value = frequencia;
    gain.gain.setValueAtTime(volume, ctx.currentTime + inicio);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + inicio + duracao);
    osc.start(ctx.currentTime + inicio);
    osc.stop(ctx.currentTime + inicio + duracao);
  }

  function varredura(ctx, freqInicial, freqFinal, inicio, duracao, volume) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freqInicial, ctx.currentTime + inicio);
    osc.frequency.linearRampToValueAtTime(freqFinal, ctx.currentTime + inicio + duracao);
    gain.gain.setValueAtTime(volume, ctx.currentTime + inicio);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + inicio + duracao + 0.05);
    osc.start(ctx.currentTime + inicio);
    osc.stop(ctx.currentTime + inicio + duracao + 0.05);
  }

  // 6 estilos de alarme que o usuário pode escolher na tela de Alertas.
  // "intervalo" é de quanto em quanto tempo (ms) o ciclo se repete enquanto o alarme tocar.
  const ALARMES = {
    classico: {
      label: 'Clássico',
      intervalo: 1000,
      tocar(ctx) {
        bipe(ctx, 660, 0, 0.22, 0.25);
      },
    },
    urgente: {
      label: 'Urgente (triplo)',
      intervalo: 1200,
      tocar(ctx) {
        bipe(ctx, 880, 0, 0.15, 0.3);
        bipe(ctx, 880, 0.22, 0.15, 0.3);
        bipe(ctx, 880, 0.44, 0.15, 0.3);
      },
    },
    sirene: {
      label: 'Sirene',
      intervalo: 1500,
      tocar(ctx) {
        varredura(ctx, 400, 900, 0, 0.6, 0.25);
        varredura(ctx, 900, 400, 0.65, 0.6, 0.25);
      },
    },
    alternado: {
      label: 'Alternado',
      intervalo: 1600,
      tocar(ctx) {
        bipe(ctx, 700, 0, 0.18, 0.28);
        bipe(ctx, 500, 0.22, 0.18, 0.28);
        bipe(ctx, 700, 0.44, 0.18, 0.28);
        bipe(ctx, 500, 0.66, 0.18, 0.28);
      },
    },
    digital: {
      label: 'Digital',
      intervalo: 900,
      tocar(ctx) {
        bipe(ctx, 1200, 0, 0.06, 0.22);
        bipe(ctx, 1200, 0.1, 0.06, 0.22);
        bipe(ctx, 1200, 0.2, 0.06, 0.22);
      },
    },
    suave: {
      label: 'Suave',
      intervalo: 1900,
      tocar(ctx) {
        bipe(ctx, 523, 0, 0.35, 0.18);
        bipe(ctx, 659, 0.18, 0.4, 0.18);
      },
    },
  };

  function listarEstilosAlarme() {
    return Object.keys(ALARMES).map((id) => ({ id, label: ALARMES[id].label }));
  }

  function obterEstiloAlarme() {
    const salvo = localStorage.getItem(ESTILO_PREF_KEY);
    return salvo && ALARMES[salvo] ? salvo : 'classico';
  }

  function definirEstiloAlarme(id) {
    if (ALARMES[id]) localStorage.setItem(ESTILO_PREF_KEY, id);
  }

  // ---------- Alarme contínuo + aviso pra parar ----------
  // O alarme toca em loop (não é só um beep único) até a pessoa clicar em "Parar alarme"
  // ou navegar até a tela de Alertas (o que já encerra esse script e para o som).
  let cicloAlarmeId = null;

  function iniciarAlarme() {
    pararAlarme();
    const estilo = ALARMES[obterEstiloAlarme()] || ALARMES.classico;
    const disparar = () => {
      const ctx = getAudioCtx();
      if (ctx.state === 'suspended') ctx.resume();
      estilo.tocar(ctx);
    };
    disparar();
    cicloAlarmeId = setInterval(disparar, estilo.intervalo);
  }

  function pararAlarme() {
    if (cicloAlarmeId) {
      clearInterval(cicloAlarmeId);
      cicloAlarmeId = null;
    }
    removerBanner();
  }

  function escaparHtml(texto) {
    const div = document.createElement('div');
    div.textContent = String(texto == null ? '' : texto);
    return div.innerHTML;
  }

  function mostrarBannerParar(alerta) {
    removerBanner();
    const banner = document.createElement('div');
    banner.id = 'radar-alarme-banner';
    banner.style.cssText =
      'position:fixed;bottom:20px;right:20px;z-index:99999;background:#1f2937;color:#fff;' +
      'padding:14px 18px;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.35);' +
      'display:flex;align-items:center;gap:12px;font-family:Inter,system-ui,sans-serif;' +
      'font-size:14px;max-width:340px;';
    const rotulo = alerta && alerta.palavraEncontrada ? escaparHtml(alerta.palavraEncontrada) : 'novo alerta';
    banner.innerHTML =
      '<span style="flex:1;">🔔 Alerta: <strong>' + rotulo + '</strong></span>' +
      '<button type="button" id="radar-parar-alarme-btn" style="background:#ef4444;color:#fff;border:none;' +
      'border-radius:6px;padding:6px 12px;font-size:13px;font-weight:600;cursor:pointer;">Parar alarme</button>';
    document.body.appendChild(banner);
    document.getElementById('radar-parar-alarme-btn').addEventListener('click', pararAlarme);
  }

  function removerBanner() {
    const el = document.getElementById('radar-alarme-banner');
    if (el) el.remove();
  }

  function notificar(alerta) {
    if ((alerta.tipoNotificacao || 'padrao') !== 'silencioso') {
      iniciarAlarme();
      mostrarBannerParar(alerta);
    }

    if (!preferenciaAtiva() || !notificacaoPermitida) return;
    const titulo = alerta.uasg ? `Novo alerta — UASG ${alerta.uasg}` : 'Novo alerta — PEPACORP LICITA';
    new Notification(titulo, {
      body: `${alerta.palavraEncontrada}: ${alerta.mensagem || ''}`.slice(0, 180),
      tag: alerta.id,
    });
  }

  function testarAlarme(estiloId) {
    if (estiloId) definirEstiloAlarme(estiloId);
    pedirPermissao();
    notificar({ id: 'teste-' + Date.now(), palavraEncontrada: 'teste de alarme', mensagem: 'Esta é uma notificação de teste do PEPACORP LICITA.', tipoNotificacao: 'padrao' });
  }

  // ---------- Conexão em tempo real com o servidor ----------
  let eventSource = null;
  const ouvintes = new Set();

  function conectar() {
    if (eventSource || !('EventSource' in window)) return;
    eventSource = new EventSource('/api/eventos');
    eventSource.addEventListener('alerta', (evento) => {
      try {
        const alerta = JSON.parse(evento.data);
        notificar(alerta);
        ouvintes.forEach((cb) => cb(alerta));
      } catch (err) {
        console.error('Falha ao processar alerta recebido em tempo real:', err);
      }
    });
    eventSource.onerror = () => {
      // EventSource já reconecta sozinho (com backoff do próprio navegador).
    };
  }

  conectar();

  window.RadarNotificacoes = {
    preferenciaAtiva,
    definirPreferencia,
    pedirPermissao,
    listarEstilosAlarme,
    obterEstiloAlarme,
    definirEstiloAlarme,
    pararAlarme,
    testarAlarme,
    aoReceberAlerta: (cb) => ouvintes.add(cb),
  };
})();
