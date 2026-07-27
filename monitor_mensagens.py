# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
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

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log_atualizacoes.log")

def formatar_label(item):
    uasg = item.get("uasg")
    numero = item.get("numeroPregao")
    ano = item.get("anoPregao")
    if uasg and numero:
        ano_txt = f"/{ano}" if ano else ""
        return f"UASG {uasg} — Pregão {numero}{ano_txt}"
    return f"ID {item['idCompra']}"

def registrar_log(id_compra, status, detalhe="", label=""):
    timestamp = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    referencia = f"{label} (ID {id_compra})" if label else f"Licitacao {id_compra}"
    linha = f"[{timestamp}] {referencia} - {status}"
    if detalhe:
        linha += f" - {detalhe}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception as e:
        print(f"[aviso] Nao foi possivel gravar no log: {e}")

TEMPO_CARREGAR_CHROME = 5      # segundos esperando o Chrome abrir
TEMPO_CARREGAR_PAGINA = 15     # segundos esperando a página carregar
TEMPO_ABRIR_MENSAGENS = 2.5    # segundos esperando a aba de mensagens carregar

# Mesma lista usada em monitoramento.html (SITUACOES_ALERTA) para identificar licitacoes encerradas.
SITUACOES_ENCERRADAS = ['anulad', 'revogad', 'suspens', 'fracassad', 'desert', 'cancelad']

def esta_encerrada(situacao):
    s = (situacao or '').lower()
    return any(termo in s for termo in SITUACOES_ENCERRADAS)

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
    req_url = f"{url}/rest/v1/pregoes_monitorados?select=id_compra,uasg,numero_pregao,ano_pregao,favorito,situacao"
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
            return [
                {
                    "idCompra": item["id_compra"],
                    "uasg": item.get("uasg"),
                    "numeroPregao": item.get("numero_pregao"),
                    "anoPregao": item.get("ano_pregao"),
                    "favorito": bool(item.get("favorito")),
                    "situacao": item.get("situacao"),
                }
                for item in res_json if "id_compra" in item
            ]
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
            return [
                {
                    "idCompra": item["idCompra"],
                    "uasg": item.get("uasg"),
                    "numeroPregao": item.get("numeroPregao"),
                    "anoPregao": item.get("anoPregao"),
                    "favorito": bool(item.get("favorito")),
                    "situacao": item.get("situacao"),
                }
                for item in itens if "idCompra" in item
            ]
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

# Quando a compra nao tem chat de mensagens disponivel, o ComprasNet mostra essa tela
# de "Informacoes adicionais da compra" em vez do painel de mensagens. Na pratica isso
# so acontece com compras encerradas (revogadas/canceladas/etc), entao o bot marca a
# situacao como Revogada para que a licitacao saia da varredura a partir da proxima vez.
MARCADOR_SEM_CHAT = "Informações adicionais da compra"

def marcar_como_revogada(id_compra):
    url = f"{base_url}/api/monitorados/{id_compra}/situacao"
    data = json.dumps({"situacao": "Revogada (detectada automaticamente)"}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='PATCH')
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"[erro] Falha ao marcar licitacao como revogada: {e}")
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

def mesclar_normais_favoritas(normais, favoritas):
    # Intercala 1 normal + 1 favorita, sempre mantendo esse padrao pelo resto da
    # varredura. Como normalmente ha muito menos favoritas que normais, as favoritas
    # sao revisitadas em ciclo (voltam para a primeira quando a lista acaba) - assim
    # elas continuam sendo analisadas repetidamente junto de cada normal nova aberta,
    # em vez de sumir da intercalacao assim que a lista de favoritas se esgota.
    if not favoritas:
        return list(normais)
    if not normais:
        return list(favoritas)

    mesclado = []
    for i, normal in enumerate(normais):
        mesclado.append(normal)
        mesclado.append(favoritas[i % len(favoritas)])
    return mesclado

def processar_lista_licitacoes(ids_monitorados):
    total_recebido = len(ids_monitorados)
    ids_monitorados = [item for item in ids_monitorados if not esta_encerrada(item.get("situacao"))]
    ignoradas = total_recebido - len(ids_monitorados)
    if ignoradas:
        print(f"[info] Ignorando {ignoradas} licitacoes encerradas (suspensa/revogada/anulada/etc) da varredura.")

    normais = [item for item in ids_monitorados if not item.get("favorito")]
    favoritas = [item for item in ids_monitorados if item.get("favorito")]
    ids_monitorados = mesclar_normais_favoritas(normais, favoritas)

    total = len(ids_monitorados)
    if total == 0:
        return

    print(f"[info] Encontradas {len(normais)} licitacoes normais e {len(favoritas)} favoritas. Iniciando pipeline mesclado de 2 abas...")

    def obter_url(id_c):
        return f"https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra={id_c}"

    # Limpa a área de transferência antes de começar
    pyperclip.copy("")
    
    # 1. Abre os 2 primeiros pregões (ou menos, se houver menos de 2 no total)
    lote_inicial = min(2, total)
    for idx in range(lote_inicial):
        item = ids_monitorados[idx]
        id_compra = item["idCompra"]
        label = formatar_label(item)
        url = obter_url(id_compra)
        if idx == 0:
            print(f"[agente] Abrindo {label} em nova janela isolada...")
            subprocess.run(f'start chrome --new-window "{url}"', shell=True)
        else:
            print(f"[agente] Abrindo {label} em nova aba...")
            subprocess.run(f'start chrome "{url}"', shell=True)
        time.sleep(1.0) # delay curto para o Chrome processar a abertura

    # Espera silenciosa inicial para que as 2 abas de pregões carreguem em paralelo
    print(f"[agente] Aguardando {TEMPO_CARREGAR_PAGINA}s o carregamento concorrente inicial das páginas...")
    time.sleep(TEMPO_CARREGAR_PAGINA)

    posicao = carregar_posicao_botao()
    
    # Se não houver posição cadastrada, calibra usando a primeira aba de pregão (Aba 1)
    if not posicao:
        # Foca a primeira aba de pregão (Aba 1)
        pyautogui.hotkey('ctrl', '1')
        time.sleep(0.5)
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

    # Controla qual será o próximo pregão a ser pré-carregado no Chrome
    proximo_para_abrir = lote_inicial

    for idx, item in enumerate(ids_monitorados):
        id_compra = item["idCompra"]
        tipo = "favorita" if item.get("favorito") else "normal"
        label = formatar_label(item)
        label_exibicao = f"★ {label}" if tipo == "favorita" else label
        print(f"\n--- Processando Licitacao {idx + 1} de {total} | ID: {id_compra} | {label_exibicao} ---")
        inicio_item = time.time()

        # 1. Traz o foco do Chrome para a primeira aba de pregão ativa (Aba 1, Ctrl + 1)
        print("[agente] Focando na aba da licitação atual...")
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', '1')
        time.sleep(0.5)

        # 2. Clica no botão Mensagens
        print("[agente] Clicando no botão Mensagens...")
        pyautogui.click(x=posicao["x"], y=posicao["y"])

        # 3. Espera silenciosamente a aba de mensagens carregar
        time.sleep(TEMPO_ABRIR_MENSAGENS)

        # 4. Foca no chat e copia as mensagens (Ctrl+A, Ctrl+C)
        print("[agente] Copiando mensagens...")
        try:
            width, height = pyautogui.size()
            pyautogui.click(x=width // 2, y=height // 2)
            time.sleep(0.3)
        except Exception as e:
            pass

        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.6)

        # 5. Salva o clipboard bruto imediatamente
        texto_bruto = pyperclip.paste()

        # 6. Fecha a aba da licitação processada (Ctrl+W). As mensagens abrem na mesma
        # aba do pregão (nao em aba separada), entao um unico fechamento e suficiente -
        # um segundo Ctrl+W aqui fecharia a aba seguinte (ou a janela, se so sobrar uma).
        print("[agente] Fechando aba da licitação processada...")
        pyautogui.hotkey('ctrl', 'w')
        time.sleep(0.3)
        
        # 7. Processa o texto copiado e faz a chamada de rede para a API/banco
        if MARCADOR_SEM_CHAT in texto_bruto:
            # A pagina nao abriu o chat de mensagens (mostrou a tela de informacoes da
            # compra) - isso indica que a licitacao foi revogada/encerrada. Marca a
            # situacao no banco para ela sair da varredura a partir da proxima vez.
            print(f"[revogada] {label} (ID {id_compra}) sem chat de mensagens - marcada como revogada e removida da varredura.")
            marcar_como_revogada(id_compra)
            registrar_log(id_compra, "REVOGADA", "Sem chat de mensagens (tela de informacoes da compra)", label)
        else:
            texto_limpo = extrair_mensagens(texto_bruto)
            if not texto_limpo.strip():
                print("ERRO: Nenhuma mensagem detectada. Talvez a pagina nao tenha carregado as mensagens a tempo.")
                registrar_log(id_compra, "FALHA", "Nenhuma mensagem detectada na pagina", label)
            else:
                resultado_api = enviar_para_api(texto_limpo, id_compra)
                if resultado_api and resultado_api.get("ok"):
                    tot = resultado_api.get('total', 0)
                    novas = resultado_api.get('novas', 0)
                    print(f"[ok] A aplicacao encontrou {tot} msgs no total. {novas} novas salvas!")
                    registrar_log(id_compra, "OK", f"{tot} msgs no total, {novas} novas", label)
                else:
                    print("[aviso] Falha na integracao com a API.")
                    registrar_log(id_compra, "FALHA", "Falha na integracao com a API", label)

        # 8. Abre o próximo pregão da fila (se houver), somente apos a analise da aba anterior
        if proximo_para_abrir < total:
            prox_item = ids_monitorados[proximo_para_abrir]
            prox_id = prox_item["idCompra"]
            prox_label = formatar_label(prox_item)
            prox_tipo = "favorita" if prox_item.get("favorito") else "normal"
            prox_url = obter_url(prox_id)
            print(f"[agente] Pré-carregando {prox_label} ({prox_tipo}) em nova aba (segundo plano)...")
            subprocess.run(f'start chrome "{prox_url}"', shell=True)
            proximo_para_abrir += 1
            # Delay para garantir que o Chrome concluiu a mudanca de foco e abertura
            time.sleep(1.5)

        # 9. Registra o tempo total gasto nesta licitacao, separado por tipo (usado pelo painel de status)
        tempo_gasto = time.time() - inicio_item
        print(f"[tempo] Licitacao {id_compra} ({tipo}) processada em {tempo_gasto:.1f}s")

def main():
    parser = argparse.ArgumentParser(description="Bot de monitoramento de mensagens (Versao PyAutoGUI / Nuvem).")
    parser.add_argument("--id", type=str, help="ID da licitacao especifica para verificar.")
    parser.add_argument("--no-wait", action="store_true", help="Ignora a espera de recalibracao e usa as coordenadas salvas imediatamente.")
    parser.add_argument("--resume-id", type=str, help="ID da licitacao onde a varredura anterior parou. A lista sera reordenada para continuar a partir dela.")
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
        ids_monitorados = [{"idCompra": args.id, "uasg": None, "numeroPregao": None, "anoPregao": None, "favorito": False}]
        print(f"[info] Rodando para um unico ID especifico via argumento: {args.id}")
    else:
        ids_monitorados = obter_licitacoes()

    if not ids_monitorados:
        print("[erro] Nenhuma licitacao retornada pela API ou a API esta offline.")
        return

    if args.resume_id:
        indices = [i for i, item in enumerate(ids_monitorados) if str(item["idCompra"]) == str(args.resume_id)]
        if indices:
            idx = indices[0]
            ids_monitorados = ids_monitorados[idx:] + ids_monitorados[:idx]
            print(f"[info] Retomando varredura anterior a partir da licitacao ID: {args.resume_id}")
        else:
            print(f"[aviso] ID de retomada {args.resume_id} nao encontrado na lista atual. Iniciando do começo.")

    processar_lista_licitacoes(ids_monitorados)
    print("\n[bot] PROCESSAMENTO FINALIZADO.")

if __name__ == "__main__":
    main()
