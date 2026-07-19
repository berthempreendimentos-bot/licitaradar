# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
import subprocess
import datetime
import urllib.request
import urllib.error
import json
import re
import argparse

import pyautogui
pyautogui.FAILSAFE = False
import pyperclip

import os
base_url = os.environ.get("API_BASE_URL", "http://localhost:3001")
API_URL_MONITORADOS = f"{base_url}/api/monitorados"
API_URL_BASE = f"{base_url}/api/mensagens"

TEMPO_CARREGAR_CHROME = 5      # segundos esperando o Chrome abrir
TEMPO_CARREGAR_PAGINA = 15     # segundos esperando a página carregar
TEMPO_ABRIR_MENSAGENS = 5      # segundos esperando a aba de mensagens carregar

TEMPO_ABRIR_MENSAGENS = 5      # segundos esperando a aba de mensagens carregar

# O mouse não será mais utilizado! Usaremos Selenium puro para cliques em background.

def obter_licitacoes():
    print("[agente] Solicitando lista de licitacoes do banco de dados...")
    req = urllib.request.Request(API_URL_MONITORADOS, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode()
            res_json = json.loads(res_body)
            itens = res_json.get("itens", [])
            return [item["idCompra"] for item in itens if "idCompra" in item]
    except Exception as e:
        print(f"[erro] Falha ao obter lista de licitacoes: {e}")
        return []

def extrair_mensagens(texto_bruto):
    mensagens = []
    buffer = []
    regex_data = re.compile(r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}')
    
    for linha in texto_bruto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
            
        buffer.append(linha)
        
        match = regex_data.search(linha)
        if match and linha.endswith(match.group()):
            msg_text = "\n".join(buffer)
            if not re.match(r'(?i)^\s*Mensagem d[oa]\b', msg_text):
                msg_text = "Mensagem do Sistema\n" + msg_text
            mensagens.append(msg_text)
            buffer = []
    return "\n\n".join(mensagens)

def enviar_para_api(texto_limpo, id_compra):
    url = f"{API_URL_BASE}/{id_compra}"
    print(f"[agente] Enviando {len(texto_limpo.split('Mensagem d')) - 1} mensagens limpas para a API...")
    data = json.dumps({"texto": texto_limpo}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[erro] O servidor retornou erro {e.code}: {e.read().decode()}")
        return None
    except Exception as e:
        print(f"[erro] Falha de conexao com a API: {e}")
        return None

def carregar_posicao_botao():
    arquivo_posicao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posicao_botao.json")
    if os.path.exists(arquivo_posicao):
        try:
            with open(arquivo_posicao, 'r') as f:
                return json.load(f)
        except:
            pass
    return None

def salvar_posicao_botao(x, y):
    arquivo_posicao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posicao_botao.json")
    with open(arquivo_posicao, 'w') as f:
        json.dump({"x": x, "y": y}, f)

def abrir_chrome_e_processar(url, id_compra):
    print(f"[agente] Acessando {url} (abrindo no Chrome padrão)...")
    
    posicao = carregar_posicao_botao()
    if not posicao:
        print("\n" + "="*70)
        print("PRIMEIRA EXECUÇÃO: CONFIGURAÇÃO DO CLIQUE")
        print("O robô precisa saber onde fica o botão 'Mensagens' na sua tela.")
        print("Vou abrir a página agora. Assim que ela carregar, coloque o mouse")
        print("EXATAMENTE em cima do botão 'Mensagens' e deixe ele lá parado.")
        print("O robô vai capturar a posição em 15 segundos...")
        print("="*70 + "\n")
    
    # Limpa a área de transferência antes de começar
    pyperclip.copy("")
    
    # Abre o Chrome oficial do usuário
    subprocess.run(f'start chrome "{url}"', shell=True)
    
    print(f"[agente] Aguardando {TEMPO_CARREGAR_PAGINA}s o carregamento da página...")
    time.sleep(TEMPO_CARREGAR_PAGINA)
    
    if not posicao:
        x, y = pyautogui.position()
        print(f"[agente] Posição do mouse capturada: X={x}, Y={y}. Salvando para as próximas vezes.")
        salvar_posicao_botao(x, y)
        posicao = {"x": x, "y": y}
    
    print("[agente] Clicando no botão Mensagens...")
    pyautogui.click(x=posicao["x"], y=posicao["y"])
    
    print(f"[agente] Aguardando {TEMPO_ABRIR_MENSAGENS}s a aba de mensagens abrir...")
    time.sleep(TEMPO_ABRIR_MENSAGENS)
    
    print("[agente] Copiando texto da tela (Ctrl+A, Ctrl+C)...")
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(1)
    
    # Fechar a aba
    print("[agente] Fechando aba (Ctrl+W)...")
    pyautogui.hotkey('ctrl', 'w')
    
    texto_bruto = pyperclip.paste()
    
    texto_limpo = extrair_mensagens(texto_bruto)
    
    if not texto_limpo.strip():
        print("ERRO: Nenhuma mensagem detectada. Talvez a pagina nao tenha carregado as mensagens a tempo.")
    else:
        resultado_api = enviar_para_api(texto_limpo, id_compra)
        if resultado_api and resultado_api.get("ok"):
            tot = resultado_api.get('total', 0)
            novas = resultado_api.get('novas', 0)
            print(f"[ok] A aplicacao encontrou {tot} msgs no total. {novas} novas salvas!")
        else:
            print("[aviso] Falha na integracao com a API.")

def processar_licitacao(id_compra):
    url_licitacao = f"https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra={id_compra}"
    abrir_chrome_e_processar(url_licitacao, id_compra)


def main():
    parser = argparse.ArgumentParser(description="Bot de monitoramento de mensagens (Versao PyAutoGUI / Nuvem).")
    parser.add_argument("--id", type=str, help="ID da licitacao especifica para verificar.")
    args = parser.parse_args()

    print("[agente] Iniciando... NAO use o mouse/teclado durante a execucao.")
    print("[agente] Para abortar, jogue o mouse no canto superior esquerdo da tela.\n")

    if args.id:
        ids_monitorados = [args.id]
        print(f"[info] Rodando para um unico ID especifico via argumento: {args.id}")
    else:
        ids_monitorados = obter_licitacoes()

    if not ids_monitorados:
        print("[erro] Nenhuma licitacao retornada pela API ou a API esta offline.")
        return
        
    print(f"[info] Encontradas {len(ids_monitorados)} licitacoes. Iniciando automacao fisica...")
    
    for index, id_compra in enumerate(ids_monitorados, start=1):
        print(f"\n--- Processando Licitacao {index} de {len(ids_monitorados)} (ID: {id_compra}) ---")
        processar_licitacao(id_compra)
        print("-" * 40)
        
    print("\n[bot] PROCESSAMENTO FINALIZADO.")

if __name__ == "__main__":
    main()
