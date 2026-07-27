# -*- coding: utf-8 -*-
"""Watchdog: fica de olho se o bot_infinito.py está rodando neste PC.

Roda em paralelo (janela separada) e verifica periodicamente a lista de
processos do Windows. Se o bot_infinito.py sumir da lista, dispara um alerta
pela API (som + pop-up em qualquer aba do RADAR aberta + mensagem no
WhatsApp, se configurado). Quando ele voltar a rodar, avisa também.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import subprocess
import time
import datetime
import json
import os
import urllib.request

# Troque para a URL do seu deploy na Vercel (o mesmo valor usado em bot_infinito.py).
# Exemplo: API_BASE_URL = "https://meu-comprasnet.vercel.app"
API_BASE_URL = "http://localhost:3001"

INTERVALO_VERIFICACAO_SEGUNDOS = 120  # a cada 2 minutos
NOME_PROCESSO_ALVO = "bot_infinito.py"

ARQUIVO_ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot_watchdog_estado.json")


def bot_esta_rodando():
    try:
        resultado = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                "| Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True, text=True, timeout=15,
        )
        return NOME_PROCESSO_ALVO in (resultado.stdout or "")
    except Exception as e:
        print(f"[watchdog] Erro ao checar processos: {e}")
        return True  # Falha na checagem não deve gerar alarme falso.


def carregar_estado():
    if os.path.exists(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"rodando": True, "alerta_enviado": False}


def salvar_estado(estado):
    with open(ARQUIVO_ESTADO, "w") as f:
        json.dump(estado, f)


def enviar_alerta(mensagem, tipo="urgente"):
    url = f"{API_BASE_URL}/api/bot/alerta"
    data = json.dumps({"mensagem": mensagem, "tipoNotificacao": tipo}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        print(f"[watchdog] Alerta enviado: {mensagem}")
    except Exception as e:
        print(f"[watchdog] Falha ao enviar alerta pra API ({url}): {e}")


def main():
    print("=" * 60)
    print("WATCHDOG DO bot_infinito.py")
    print(f"Verificando a cada {INTERVALO_VERIFICACAO_SEGUNDOS}s se o robô está rodando neste PC.")
    print(f"Alvo da API de alerta: {API_BASE_URL}")
    print("Deixe esta janela aberta junto com a do bot_infinito.py.")
    print("=" * 60)

    estado = carregar_estado()

    while True:
        rodando = bot_esta_rodando()
        agora = datetime.datetime.now().strftime("%H:%M:%S")

        if rodando:
            if not estado["rodando"] and estado["alerta_enviado"]:
                print(f"[{agora}] Robô voltou a rodar.")
                enviar_alerta(
                    "O robô bot_infinito.py voltou a rodar normalmente.",
                    tipo="padrao",
                )
            estado["rodando"] = True
            estado["alerta_enviado"] = False
        else:
            print(f"[{agora}] bot_infinito.py NÃO está rodando neste PC.")
            if not estado["alerta_enviado"]:
                enviar_alerta(
                    "O robô bot_infinito.py PAROU de rodar neste PC. "
                    "As mensagens da Sala de Disputa deixaram de ser coletadas.",
                    tipo="urgente",
                )
                estado["alerta_enviado"] = True
            estado["rodando"] = False

        salvar_estado(estado)
        time.sleep(INTERVALO_VERIFICACAO_SEGUNDOS)


if __name__ == "__main__":
    main()
