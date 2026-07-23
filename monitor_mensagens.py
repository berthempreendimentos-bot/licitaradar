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

def carregar_credenciais_supabase():
    dir_atual = os.path.dirname(os.path.abspath(__file__))
    possiveis_caminhos = [
        os.path.join(dir_atual, "server", ".env"),
        os.path.join(os.path.dirname(dir_atual), "server", ".env"),
        os.path.join(dir_atual, ".env"),
    ]
    for caminho in possiveis_caminhos:
        if os.path.exists(caminho):
            try:
                credenciais = {}
                with open(caminho, "r", encoding="utf-8") as f:
                    for line in f:
                        line_stripped = line.strip()
                        if "=" in line_stripped and not line_stripped.startswith("#"):
                            k, v = line_stripped.split("=", 1)
                            credenciais[k.strip()] = v.strip()
                if credenciais.get("SUPABASE_URL") and credenciais.get("SUPABASE_SERVICE_KEY"):
                    return credenciais
            except Exception as e:
                print(f"[aviso] Erro ao ler arquivo .env em {caminho}: {e}")
    return None

def obter_licitacoes_supabase_fallback():
    print("[agente] API offline. Tentando obter lista de licitacoes diretamente do Supabase...")
    cred = carregar_credenciais_supabase()
    if not cred:
        print("[erro] Credenciais do Supabase nao encontradas em server/.env")
        return []
    
    url = cred["SUPABASE_URL"]
    key = cred["SUPABASE_SERVICE_KEY"]
    req_url = f"{url}/rest/v1/pregoes_monitorados?select=id_compra"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json"
    }
    req = urllib.request.Request(req_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode()
            res_json = json.loads(res_body)
            return [item["id_compra"] for item in res_json if "id_compra" in item]
    except Exception as e:
        print(f"[erro] Falha ao obter licitacoes diretamente do Supabase: {e}")
        return []

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
        print(f"[erro] Falha ao obter lista de licitacoes via API: {e}")
        return obter_licitacoes_supabase_fallback()

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

    # Limpa a área de transferência antes de começar
    pyperclip.copy("")

    # Abre o Chrome oficial do usuário
    subprocess.run(f'start chrome "{url}"', shell=True)

    # Espera ativa de carregamento da página
    print("[agente] Aguardando a página carregar (espera ativa)...")
    carregou = False
    timeout_pag = 30  # segundos máximo
    start_pag = time.time()
    
    # Dá um tempo mínimo para o Chrome abrir
    time.sleep(2)
    try:
        width, height = pyautogui.size()
        pyautogui.click(x=width // 2, y=height // 2)
    except Exception as e:
        print(f"[aviso] Não foi possível obter o tamanho da tela ou focar: {e}")
        width, height = 1920, 1080  # fallback padrão

    while time.time() - start_pag < timeout_pag:
        try:
            # Clica no centro da tela para focar a nova aba/janela do Chrome
            pyautogui.click(x=width // 2, y=height // 2)
            time.sleep(0.3)
            pyperclip.copy("")
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.3)
            
            texto = pyperclip.paste()
            texto_lower = texto.lower()
            
            # Verifica termos específicos que indicam que a página carregou
            if "acompanhamento" in texto_lower or "mensagens" in texto_lower or "uasg" in texto_lower or "compra" in texto_lower:
                print(f"[agente] Página carregada com sucesso em {int(time.time() - start_pag)}s!")
                carregou = True
                break
        except Exception as e:
            print(f"[aviso] Erro na espera ativa: {e}")
            
        print("[agente] Página ainda carregando, aguardando...")
        time.sleep(1.5)

    if not carregou:
        print(f"[aviso] Tempo limite esgotado esperando a página carregar. Prosseguindo...")
        time.sleep(2)

    if not posicao:
        print("\n" + "="*70)
        print("PRIMEIRA EXECUÇÃO: CONFIGURAÇÃO DO CLIQUE")
        print("A página já deve ter carregado. Role até achar o botão 'Mensagens'")
        print("e coloque o mouse EXATAMENTE em cima dele, sem clicar.")
        print("="*70)
        input(">>> Com o mouse sobre o botão 'Mensagens', pressione ENTER aqui... ")
        x, y = pyautogui.position()
        print(f"[agente] Posição do mouse capturada: X={x}, Y={y}. Salvando para as próximas vezes.")
        salvar_posicao_botao(x, y)
        posicao = {"x": x, "y": y}
    
    print("[agente] Clicando no botão Mensagens...")
    pyautogui.click(x=posicao["x"], y=posicao["y"])
    
    # Espera ativa da aba de mensagens
    print("[agente] Aguardando a aba de mensagens abrir (espera ativa)...")
    aba_aberta = False
    timeout_msg = 15  # segundos máximo
    start_msg = time.time()
    
    while time.time() - start_msg < timeout_msg:
        try:
            pyperclip.copy("")
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.3)
            
            texto_chat = pyperclip.paste()
            texto_chat_lower = texto_chat.lower()
            
            # Verifica se contém termos típicos do chat de mensagens
            if "mensagem do" in texto_chat_lower or "pregoeiro" in texto_chat_lower or "sistema" in texto_chat_lower or "chat" in texto_chat_lower or "voltar" in texto_chat_lower:
                print(f"[agente] Aba de mensagens aberta e carregada em {int(time.time() - start_msg)}s!")
                aba_aberta = True
                break
        except Exception as e:
            print(f"[aviso] Erro ao verificar aba de mensagens: {e}")
            
        print("[agente] Aguardando abertura das mensagens...")
        time.sleep(1.0)
        
    if not aba_aberta:
        print(f"[aviso] Tempo limite esgotado esperando a aba de mensagens. Copiando texto atual...")
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.5)
    
    # Fechar a aba do navegador
    print("[agente] Fechando aba (Ctrl+W)...")
    pyautogui.hotkey('ctrl', 'w')
    time.sleep(0.5)
    
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
    parser.add_argument("--no-wait", action="store_true", help="Ignora a espera de recalibracao e usa as coordenadas salvas imediatamente.")
    args = parser.parse_args()

    # Verifica se deseja recalibrar as coordenadas do botão
    posicao = carregar_posicao_botao()
    if posicao and not args.no_wait:
        print(f"[agente] Posicao do botao Mensagens cadastrada: X={posicao['x']}, Y={posicao['y']}")
        print("Pressione 'c' para recalibrar novas coordenadas ou ENTER para usar as atuais.")
        print("(O script continuara automaticamente com as coordenadas salvas em 5 segundos...)")
        
        try:
            import msvcrt
            start_time = time.time()
            recalibrar = False
            while time.time() - start_time < 5:
                if msvcrt.kbhit():
                    char = msvcrt.getwch().lower()
                    if char == 'c':
                        recalibrar = True
                        print("\n[agente] Recalibracao solicitada pelo usuario.")
                        break
                    elif char in ['\r', '\n']:
                        print("\n[agente] Usando coordenadas salvas.")
                        break
                time.sleep(0.05)
            
            if recalibrar:
                arquivo_posicao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posicao_botao.json")
                if os.path.exists(arquivo_posicao):
                    try:
                        os.remove(arquivo_posicao)
                        print("[agente] Coordenadas salvas removidas para recalibracao.")
                    except Exception as e:
                        print(f"[erro] Nao foi possivel remover as coordenadas salvas: {e}")
        except Exception as e:
            pass
    elif posicao and args.no_wait:
        print(f"[agente] Posicao do botao Mensagens cadastrada: X={posicao['x']}, Y={posicao['y']}. Ignorando recalibracao (--no-wait).")

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
