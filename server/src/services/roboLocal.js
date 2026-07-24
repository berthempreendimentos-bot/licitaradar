const { spawn } = require('child_process');
const path = require('path');

const PROJECT_ROOT = path.join(__dirname, '..', '..', '..');
const SCRIPT = path.join(PROJECT_ROOT, 'bot_infinito.py');
const MAX_LOG_LINHAS = 500;

let processo = null;
let iniciadoEm = null;
const log = [];

function adicionarLog(linha) {
  log.push(`[${new Date().toISOString()}] ${linha}`);
  if (log.length > MAX_LOG_LINHAS) log.shift();
}

function statusRobo() {
  return {
    rodando: processo !== null,
    pid: processo ? processo.pid : null,
    iniciadoEm,
  };
}

function iniciarRobo() {
  if (processo) return { ok: false, erro: 'O robô já está em execução.' };

  const pythonBin = process.platform === 'win32' ? 'python' : 'python3';
  processo = spawn(pythonBin, [SCRIPT], { cwd: PROJECT_ROOT, windowsHide: true });
  iniciadoEm = new Date().toISOString();
  adicionarLog('Robô iniciado.');

  processo.stdout.on('data', (chunk) => {
    chunk.toString('utf8').split(/\r?\n/).filter(Boolean).forEach(adicionarLog);
  });
  processo.stderr.on('data', (chunk) => {
    chunk.toString('utf8').split(/\r?\n/).filter(Boolean).forEach((linha) => adicionarLog(`[erro] ${linha}`));
  });
  processo.on('exit', (code) => {
    adicionarLog(`Robô encerrado (código ${code}).`);
    processo = null;
    iniciadoEm = null;
  });
  processo.on('error', (erro) => {
    adicionarLog(`Falha ao iniciar: ${erro.message}`);
    processo = null;
    iniciadoEm = null;
  });

  return { ok: true };
}

function pararRobo() {
  if (!processo) return { ok: false, erro: 'O robô não está em execução.' };

  const pid = processo.pid;
  if (process.platform === 'win32') {
    // mata a árvore de processos (bot_infinito.py chama monitor_mensagens.py como subprocesso)
    spawn('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true });
  } else {
    processo.kill('SIGTERM');
  }
  return { ok: true };
}

function obterLog() {
  return log;
}

module.exports = { iniciarRobo, pararRobo, statusRobo, obterLog };
