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
import threading
import queue
import builtins
import tkinter as tk
from tkinter import ttk

import pyautogui
pyautogui.FAILSAFE = False
import pyperclip
import pygetwindow as gw

import os

# Tela de status (janela "Capturar Mensagens"): mostra em tempo real o que o robô
# está fazendo e oferece um botão "Parar Robô" que realmente funciona - diferente do
# antigo aviso de "jogue o mouse no canto" (FAILSAFE ficava desligado acima, entao esse
# aborte nunca funcionou de fato).
PARAR_EVENTO = threading.Event()
LOG_QUEUE = queue.Queue()
ESTADO_LOCK = threading.Lock()
ESTADO_ATUAL = {
    "status": "Iniciando...",
    "atual": "-",
    "total": 0,
    "normais": 0,
    "favoritas": 0,
    "ok": 0,
    "falhas": 0,
    "revogadas": 0,
}

_print_original = builtins.print

def print(*args, **kwargs):
    _print_original(*args, **kwargs)
    try:
        LOG_QUEUE.put(" ".join(str(a) for a in args))
    except Exception:
        pass

def atualizar_estado(**kwargs):
    with ESTADO_LOCK:
        ESTADO_ATUAL.update(kwargs)

def incrementar_estado(campo):
    with ESTADO_LOCK:
        ESTADO_ATUAL[campo] = ESTADO_ATUAL.get(campo, 0) + 1

TABELA_LOCK = threading.Lock()
TABELA_LICITACOES = {}  # id_compra -> {"label", "status", "horario", "detalhe"}

def atualizar_tabela(id_compra, status, detalhe="", label=None):
    with TABELA_LOCK:
        existente = TABELA_LICITACOES.get(str(id_compra), {})
        TABELA_LICITACOES[str(id_compra)] = {
            "label": label if label is not None else existente.get("label", id_compra),
            "status": status,
            "horario": datetime.datetime.now().strftime('%H:%M:%S'),
            "detalhe": detalhe,
        }

# Rastreia a janela do Chrome aberta pelo robo (a "--new-window" isolada) para poder
# fechá-la quando a parada automática (falhas consecutivas) acontecer.
JANELA_LOCK = threading.Lock()
JANELAS_ABERTAS = []
PARADA_OBRIGATORIA_EVENTO = threading.Event()
TEMPO_ESPERA_REINICIO = 600  # 10 minutos

# Suporte ao botao "Reiniciar Robo" da janela de status: PULAR_ESPERA_EVENTO abrevia a
# espera de 10 min quando o robo ja esta parado aguardando reinicio automatico;
# REINICIAR_APOS_PARAR pede pra reiniciar assim que o robo terminar a licitacao atual
# (equivalente a clicar Parar, mas reiniciando em seguida em vez de ficar parado).
# THREAD_ROBO guarda a thread ativa para o botao saber se precisa criar uma nova.
PULAR_ESPERA_EVENTO = threading.Event()
REINICIAR_APOS_PARAR = threading.Event()
THREAD_ROBO = {"t": None}

def fechar_janelas_abertas():
    with JANELA_LOCK:
        janelas = list(JANELAS_ABERTAS)
        JANELAS_ABERTAS.clear()
    fechadas = 0
    for janela in janelas:
        try:
            janela.close()
            fechadas += 1
        except Exception:
            pass
    print(f"[agente] {fechadas} janela(s) do Chrome fechada(s) apos a parada automatica." if fechadas
          else "[agente] Nenhuma janela do Chrome encontrada para fechar.")

def espera_interrompivel(segundos):
    """Espera ate `segundos` decorrerem, checando PARAR_EVENTO/PULAR_ESPERA_EVENTO a cada 1s.
    Retorna True se foi interrompida pelo usuario clicando Parar (nao deve reiniciar)."""
    fim = time.time() + segundos
    ultimo_texto = None
    while time.time() < fim:
        if PARAR_EVENTO.is_set():
            return True
        if PULAR_ESPERA_EVENTO.is_set():
            PULAR_ESPERA_EVENTO.clear()
            print("[loop] Reinicio antecipado solicitado pelo usuario - pulando o restante da espera.")
            return False
        restante = max(0, int(fim - time.time()))
        minutos, segs = divmod(restante, 60)
        texto = f"Parada automática - reiniciando em {minutos:02d}:{segs:02d}..."
        if texto != ultimo_texto:
            atualizar_estado(status=texto)
            ultimo_texto = texto
        time.sleep(1)
    return False

base_url = os.environ.get("API_BASE_URL", "http://localhost:3001")
API_URL_MONITORADOS = f"{base_url}/api/monitorados"
API_URL_BASE = f"{base_url}/api/mensagens"

def obter_diretorio_base():
    # No .exe empacotado (PyInstaller), __file__ aponta para a pasta temporaria
    # de extracao (_MEIPASS), que some ao fechar - por isso usamos a pasta do
    # proprio .exe nesse caso, para persistir posicao/log/falhas ao lado dele.
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

DIRETORIO_BASE = obter_diretorio_base()
LOG_FILE = os.path.join(DIRETORIO_BASE, "log_atualizacoes.log")
FALHAS_FILE = os.path.join(DIRETORIO_BASE, "falhas_execucao.json")

def carregar_falhas_anteriores():
    if os.path.exists(FALHAS_FILE):
        try:
            with open(FALHAS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def salvar_falhas_atuais(ids_falhos):
    try:
        with open(FALHAS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(str(i) for i in ids_falhos), f)
    except Exception as e:
        print(f"[aviso] Nao foi possivel salvar a lista de falhas: {e}")

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

# O ComprasNet legado (cnetmobile) so conhece compras de orgaos cadastrados no SISG, cujo
# idCompra vindo do PNCP e puramente numerico (UASG+modalidade+numero+ano). Orgaos que
# publicam so pelo PNCP nacional (sem usar o ComprasNet legado) tem idCompra no formato
# "CNPJ-sequencial/ano" - abrir esse id no cnetmobile sempre cai em "compra-nao-encontrada",
# sem chat de mensagens, entao o robo nunca vai conseguir coletar nada dessas.
REGEX_ID_COMPRASNET_LEGADO = re.compile(r'^\d+$')

def eh_id_comprasnet_legado(id_compra):
    return bool(REGEX_ID_COMPRASNET_LEGADO.match(str(id_compra)))

# Circuito de seguranca: se a pesquisa falhar tantas vezes seguidas, provavelmente
# algo sistemico quebrou (Chrome fechou, posicao do botao mudou, site mudou de layout)
# e continuar so vai gerar mais falhas - melhor parar o robo e chamar atencao do usuario.
LIMITE_FALHAS_CONSECUTIVAS = 10

def esta_encerrada(situacao):
    s = (situacao or '').lower()
    return any(termo in s for termo in SITUACOES_ENCERRADAS)

# O mouse não será mais utilizado! Usaremos Selenium puro para cliques em background.

def carregar_credenciais_supabase():
    dir_atual = DIRETORIO_BASE
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
    arquivo_posicao = os.path.join(DIRETORIO_BASE, "posicao_botao.json")
    if os.path.exists(arquivo_posicao):
        try:
            with open(arquivo_posicao, 'r') as f:
                return json.load(f)
        except:
            pass
    return None

def salvar_posicao_botao(x, y):
    arquivo_posicao = os.path.join(DIRETORIO_BASE, "posicao_botao.json")
    with open(arquivo_posicao, 'w') as f:
        json.dump({"x": x, "y": y}, f)

NORMAIS_POR_FAVORITA = 4

def mesclar_normais_favoritas(normais, favoritas):
    # A cada NORMAIS_POR_FAVORITA normais abertas, intercala 1 favorita. Como
    # normalmente ha muito menos favoritas que normais, as favoritas sao revisitadas
    # em ciclo (voltam para a primeira quando a lista acaba) - assim elas continuam
    # sendo analisadas repetidamente ao longo da varredura, em vez de sumir da
    # intercalacao assim que a lista de favoritas se esgota.
    if not favoritas:
        return list(normais)
    if not normais:
        return list(favoritas)

    mesclado = []
    idx_favorita = 0
    for i, normal in enumerate(normais):
        mesclado.append(normal)
        if (i + 1) % NORMAIS_POR_FAVORITA == 0:
            mesclado.append(favoritas[idx_favorita % len(favoritas)])
            idx_favorita += 1

    # Garante ao menos uma passada pelas favoritas mesmo se houver menos de
    # NORMAIS_POR_FAVORITA normais no total.
    if idx_favorita == 0:
        mesclado.append(favoritas[0])

    return mesclado

def processar_lista_licitacoes(ids_monitorados):
    total_recebido = len(ids_monitorados)
    ids_monitorados = [item for item in ids_monitorados if not esta_encerrada(item.get("situacao"))]
    ignoradas = total_recebido - len(ids_monitorados)
    if ignoradas:
        print(f"[info] Ignorando {ignoradas} licitacoes encerradas (suspensa/revogada/anulada/etc) da varredura.")

    antes_filtro_legado = len(ids_monitorados)
    ids_monitorados = [item for item in ids_monitorados if eh_id_comprasnet_legado(item["idCompra"])]
    fora_do_comprasnet = antes_filtro_legado - len(ids_monitorados)
    if fora_do_comprasnet:
        print(f"[info] Ignorando {fora_do_comprasnet} licitacoes fora do ComprasNet legado "
              f"(idCompra em formato CNPJ, sem pagina no cnetmobile) da varredura.")

    # Prioriza quem deu falha na varredura anterior: essas licitacoes vao para o
    # inicio da fila (dentro do proprio grupo normal/favorita) para serem
    # reanalisadas logo, em vez de esperar a volta completa do ciclo ate elas.
    falhas_anteriores = carregar_falhas_anteriores()

    def priorizar_falhas(lista):
        if not falhas_anteriores:
            return lista
        prioridade = [item for item in lista if str(item["idCompra"]) in falhas_anteriores]
        resto = [item for item in lista if str(item["idCompra"]) not in falhas_anteriores]
        return prioridade + resto

    normais = priorizar_falhas([item for item in ids_monitorados if not item.get("favorito")])
    favoritas = priorizar_falhas([item for item in ids_monitorados if item.get("favorito")])
    ids_monitorados = mesclar_normais_favoritas(normais, favoritas)

    total = len(ids_monitorados)
    if total == 0:
        atualizar_estado(status="Nenhuma licitação para processar.")
        return

    falhas_desta_varredura = set()
    falhas_consecutivas = 0

    atualizar_estado(status="Executando varredura...", total=total, normais=len(normais), favoritas=len(favoritas))
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

    # Guarda a referencia da janela isolada do Chrome (aberta com --new-window acima) para
    # poder fecha-la automaticamente se a parada obrigatoria (falhas consecutivas) acontecer.
    try:
        janela_robo = gw.getActiveWindow()
        if janela_robo:
            with JANELA_LOCK:
                JANELAS_ABERTAS.append(janela_robo)
    except Exception:
        pass

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
        if PARAR_EVENTO.is_set():
            print("[loop] Parada solicitada pelo usuário. Encerrando após a licitação atual.")
            atualizar_estado(status="Parado pelo usuário.")
            salvar_falhas_atuais(falhas_desta_varredura)
            return

        id_compra = item["idCompra"]
        tipo = "favorita" if item.get("favorito") else "normal"
        label = formatar_label(item)
        label_exibicao = f"★ {label}" if tipo == "favorita" else label
        print(f"\n--- Processando Licitacao {idx + 1} de {total} | ID: {id_compra} | {label_exibicao} ---")
        atualizar_estado(status="Processando licitação...", atual=f"{idx + 1}/{total} — {label_exibicao}")
        atualizar_tabela(id_compra, "Processando...", "-", label=label_exibicao)
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
            incrementar_estado("revogadas")
            atualizar_tabela(id_compra, "REVOGADA", "Sem chat de mensagens")
            falhas_consecutivas = 0
        else:
            texto_limpo = extrair_mensagens(texto_bruto)
            if not texto_limpo.strip():
                print("ERRO: Nenhuma mensagem detectada. Talvez a pagina nao tenha carregado as mensagens a tempo.")
                registrar_log(id_compra, "FALHA", "Nenhuma mensagem detectada na pagina", label)
                falhas_desta_varredura.add(str(id_compra))
                falhas_consecutivas += 1
                incrementar_estado("falhas")
                atualizar_tabela(id_compra, "FALHA", "Nenhuma mensagem detectada")
            else:
                resultado_api = enviar_para_api(texto_limpo, id_compra)
                if resultado_api and resultado_api.get("ok"):
                    tot = resultado_api.get('total', 0)
                    novas = resultado_api.get('novas', 0)
                    print(f"[ok] A aplicacao encontrou {tot} msgs no total. {novas} novas salvas!")
                    registrar_log(id_compra, "OK", f"{tot} msgs no total, {novas} novas", label)
                    incrementar_estado("ok")
                    atualizar_tabela(id_compra, "OK", f"{tot} msgs no total, {novas} novas")
                    falhas_consecutivas = 0
                else:
                    print("[aviso] Falha na integracao com a API.")
                    registrar_log(id_compra, "FALHA", "Falha na integracao com a API", label)
                    falhas_desta_varredura.add(str(id_compra))
                    falhas_consecutivas += 1
                    incrementar_estado("falhas")
                    atualizar_tabela(id_compra, "FALHA", "Falha na integração com a API")

        if falhas_consecutivas >= LIMITE_FALHAS_CONSECUTIVAS:
            print(f"[parada_obrigatoria] {falhas_consecutivas} falhas consecutivas de pesquisa detectadas. "
                  f"Abortando a execucao - verifique o Chrome e a posicao do botao 'Mensagens' antes de reiniciar o robo.")
            atualizar_estado(status=f"Parada automática: {falhas_consecutivas} falhas consecutivas.")
            salvar_falhas_atuais(falhas_desta_varredura)
            PARADA_OBRIGATORIA_EVENTO.set()
            sys.exit(2)

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

    # Guarda quem falhou nesta varredura para a proxima chamada priorizar essas
    # licitacoes logo no inicio, em vez de esperar o ciclo completo dar a volta.
    salvar_falhas_atuais(falhas_desta_varredura)
    if falhas_desta_varredura:
        print(f"[info] {len(falhas_desta_varredura)} licitacoes com falha nesta varredura serao priorizadas na proxima.")
    atualizar_estado(status="Varredura concluída.", atual="-")

def criar_janela(args):
    root = tk.Tk()
    root.title("Capturar Mensagens - ComprasNet")
    root.geometry("640x760+40+40")
    root.attributes("-topmost", True)
    root.configure(bg="#111827")
    root.resizable(False, False)

    fonte_titulo = ("Segoe UI", 13, "bold")
    fonte_label = ("Segoe UI", 10)
    fonte_valor = ("Consolas", 10, "bold")

    tk.Label(
        root, text="🤖 CAPTURAR MENSAGENS", fg="#22d3ee", bg="#111827",
        font=fonte_titulo, justify="center"
    ).pack(pady=(14, 10))

    frame_botoes = tk.Frame(root, bg="#111827")
    frame_botoes.pack(fill="x", padx=16, pady=(0, 10))

    def ao_clicar_parar():
        PARAR_EVENTO.set()
        atualizar_estado(status="Parando o robô...")
        btn_parar.config(state="disabled", text="Robô Parado", bg="#4b5563")

    btn_parar = tk.Button(
        frame_botoes, text="🛑 Parar Robô", bg="#dc2626", fg="white",
        activebackground="#b91c1c", activeforeground="white",
        font=("Segoe UI", 9, "bold"), relief="flat", padx=10, pady=6,
        command=ao_clicar_parar
    )
    btn_parar.pack(side="left", expand=True, fill="x", padx=(0, 6))

    btn_reiniciar = tk.Button(
        frame_botoes, text="🔄 Reiniciar Robô", bg="#2563eb", fg="white",
        activebackground="#1d4ed8", activeforeground="white",
        font=("Segoe UI", 9, "bold"), relief="flat", padx=10, pady=6,
        command=lambda: ao_clicar_reiniciar(args)
    )
    btn_reiniciar.pack(side="left", expand=True, fill="x", padx=(6, 0))

    frame_resumo = tk.Frame(root, bg="#111827")
    frame_resumo.pack(fill="x", padx=16)

    def linha(label_txt):
        frame = tk.Frame(frame_resumo, bg="#111827")
        frame.pack(fill="x", pady=3)
        tk.Label(frame, text=label_txt, fg="#9ca3af", bg="#111827", font=fonte_label, anchor="w").pack(side="left")
        valor = tk.Label(
            frame, text="-", fg="#f9fafb", bg="#111827", font=fonte_valor,
            anchor="e", justify="right", wraplength=280
        )
        valor.pack(side="right")
        return valor

    lbl_status = linha("Status:")
    lbl_atual = linha("Licitação atual:")
    lbl_total = linha("Licitações na varredura:")
    lbl_ok = linha("Total OK:")
    lbl_falhas = linha("Total falhas:")
    lbl_revogadas = linha("Revogadas (auto):")

    tk.Label(
        root, text="Licitações lidas nesta varredura", fg="#9ca3af", bg="#111827", font=fonte_label, anchor="w"
    ).pack(fill="x", padx=16, pady=(12, 4))

    frame_tabela = tk.Frame(root, bg="#111827")
    frame_tabela.pack(fill="both", expand=True, padx=16, pady=(0, 10))

    estilo = ttk.Style()
    estilo.theme_use("clam")
    estilo.configure(
        "Treeview",
        background="#1f2937",
        fieldbackground="#1f2937",
        foreground="#f9fafb",
        rowheight=24,
        borderwidth=0,
    )
    estilo.configure("Treeview.Heading", background="#374151", foreground="#e5e7eb", font=("Segoe UI", 9, "bold"))
    estilo.map("Treeview", background=[("selected", "#2563eb")])

    colunas = ("id", "status", "horario", "detalhe")
    tabela = ttk.Treeview(frame_tabela, columns=colunas, show="headings", height=8)
    tabela.heading("id", text="Licitação")
    tabela.heading("status", text="Status")
    tabela.heading("horario", text="Horário")
    tabela.heading("detalhe", text="Detalhe")
    tabela.column("id", width=220, anchor="w")
    tabela.column("status", width=90, anchor="center")
    tabela.column("horario", width=70, anchor="center")
    tabela.column("detalhe", width=180, anchor="w")

    scrollbar_tabela = ttk.Scrollbar(frame_tabela, orient="vertical", command=tabela.yview)
    tabela.configure(yscrollcommand=scrollbar_tabela.set)
    tabela.pack(side="left", fill="both", expand=True)
    scrollbar_tabela.pack(side="right", fill="y")

    tabela.tag_configure("ok", foreground="#4ade80")
    tabela.tag_configure("falha", foreground="#f87171")
    tabela.tag_configure("processando", foreground="#facc15")
    tabela.tag_configure("revogada", foreground="#fb923c")

    tk.Label(
        root, text="Saída do robô", fg="#9ca3af", bg="#111827", font=fonte_label, anchor="w"
    ).pack(fill="x", padx=16, pady=(4, 4))

    frame_log = tk.Frame(root, bg="#111827")
    frame_log.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    texto_log = tk.Text(
        frame_log, bg="#1f2937", fg="#e5e7eb", insertbackground="#e5e7eb",
        font=("Consolas", 9), relief="flat", wrap="word", state="disabled", height=8
    )
    scrollbar_log = tk.Scrollbar(frame_log, command=texto_log.yview)
    texto_log.configure(yscrollcommand=scrollbar_log.set)
    texto_log.pack(side="left", fill="both", expand=True)
    scrollbar_log.pack(side="right", fill="y")

    def atualizar_gui():
        while True:
            try:
                linha_log = LOG_QUEUE.get_nowait()
            except queue.Empty:
                break
            estava_no_fim = texto_log.yview()[1] >= 0.999
            texto_log.configure(state="normal")
            texto_log.insert("end", linha_log + "\n")
            texto_log.configure(state="disabled")
            if estava_no_fim:
                texto_log.see("end")

        with ESTADO_LOCK:
            estado = dict(ESTADO_ATUAL)
        lbl_status.config(text=estado["status"])
        lbl_atual.config(text=estado["atual"])
        lbl_total.config(text=f"{estado['normais']} normais / {estado['favoritas']} favoritas ({estado['total']})")
        lbl_ok.config(text=str(estado["ok"]))
        lbl_falhas.config(text=str(estado["falhas"]))
        lbl_revogadas.config(text=str(estado["revogadas"]))

        with TABELA_LOCK:
            copia_tabela = dict(TABELA_LICITACOES)

        existentes = set(tabela.get_children())
        for id_removido in existentes - set(copia_tabela.keys()):
            tabela.delete(id_removido)
        existentes &= set(copia_tabela.keys())

        for id_compra, info in copia_tabela.items():
            tag = {"OK": "ok", "FALHA": "falha", "Processando...": "processando", "REVOGADA": "revogada"}.get(info["status"], "")
            valores = (info["label"], info["status"], info["horario"], info["detalhe"])
            if id_compra in existentes:
                tabela.item(id_compra, values=valores, tags=(tag,))
            else:
                tabela.insert("", "end", iid=id_compra, values=valores, tags=(tag,))

        em_analise = [id_c for id_c, info in copia_tabela.items() if info["status"] == "Processando..."]
        for posicao_linha, id_c in enumerate(em_analise):
            tabela.move(id_c, "", posicao_linha)

        if PARAR_EVENTO.is_set():
            btn_parar.config(state="disabled", text="Robô Parado", bg="#4b5563")
        else:
            btn_parar.config(state="normal", text="🛑 Parar Robô", bg="#dc2626")
            root.attributes("-topmost", True)

        root.after(300, atualizar_gui)

    def ao_fechar_janela():
        PARAR_EVENTO.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", ao_fechar_janela)

    atualizar_gui()
    root.mainloop()

def main():
    parser = argparse.ArgumentParser(description="Bot de monitoramento de mensagens (Versao PyAutoGUI / Nuvem).")
    parser.add_argument("--id", type=str, help="ID da licitacao especifica para verificar.")
    parser.add_argument("--no-wait", action="store_true", help="Ignora a espera de recalibracao e usa as coordenadas salvas imediatamente.")
    parser.add_argument("--resume-id", type=str, help="ID da licitacao onde a varredura anterior parou. A lista sera reordenada para continuar a partir dela.")
    parser.add_argument("--sem-janela", action="store_true", help="Nao abre a janela de status grafica (usado quando chamado como subprocesso pelo bot_infinito.py, que ja tem sua propria janela).")
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
                arquivo_posicao = os.path.join(DIRETORIO_BASE, "posicao_botao.json")
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

    if args.sem_janela:
        # Chamado como subprocesso pelo bot_infinito.py: sem janela grafica propria, e o
        # sys.exit(2) da parada obrigatoria deve propagar normalmente (o bot_infinito.py
        # ja trata isso lendo a saida do processo).
        executar_robo(args)
        return

    print("[agente] Para abortar, use o botao 'Parar Robo' na janela de status.\n")

    thread_robo = threading.Thread(target=loop_com_gui, args=(args,), daemon=True)
    THREAD_ROBO["t"] = thread_robo
    thread_robo.start()

    criar_janela(args)

def loop_com_gui(args):
    """Roda o robo em loop: se a parada obrigatoria (falhas consecutivas) acontecer,
    fecha as janelas do Chrome que o robo abriu e reinicia o procedimento apos
    TEMPO_ESPERA_REINICIO segundos, ate o usuario clicar em 'Parar Robo' ou o
    processamento terminar normalmente."""
    while True:
        PARADA_OBRIGATORIA_EVENTO.clear()
        try:
            executar_robo(args)
        except SystemExit:
            # sys.exit(2) disparado pela parada obrigatoria - o status e o evento ja
            # foram atualizados antes do exit, so evitamos que a excecao suba com traceback.
            pass

        if PARAR_EVENTO.is_set():
            if REINICIAR_APOS_PARAR.is_set():
                REINICIAR_APOS_PARAR.clear()
                PARAR_EVENTO.clear()
                PARADA_OBRIGATORIA_EVENTO.clear()
                with TABELA_LOCK:
                    TABELA_LICITACOES.clear()
                atualizar_estado(status="Reiniciando a pedido do usuário...", atual="-",
                                  total=0, normais=0, favoritas=0, ok=0, falhas=0, revogadas=0)
                print("[loop] Reiniciando a pedido do usuario...")
                continue
            atualizar_estado(status="Robô parado.")
            break

        if PARADA_OBRIGATORIA_EVENTO.is_set():
            fechar_janelas_abertas()
            minutos = TEMPO_ESPERA_REINICIO // 60
            print(f"[loop] Parada automatica detectada. Janelas do Chrome fechadas - reiniciando o procedimento em {minutos} minutos...")
            interrompido = espera_interrompivel(TEMPO_ESPERA_REINICIO)
            if interrompido:
                atualizar_estado(status="Robô parado.")
                break
            print("[loop] Reiniciando o procedimento apos a espera...")
            continue

        break

def ao_clicar_reiniciar(args):
    """Handler do botao 'Reiniciar Robo': se o robo ainda esta rodando (processando ou
    na espera de 10 min), pede pra reiniciar assim que possivel sem precisar de uma
    thread nova. Se ja estiver parado, cria uma thread nova do zero."""
    thread_atual = THREAD_ROBO.get("t")
    if thread_atual and thread_atual.is_alive():
        if PARADA_OBRIGATORIA_EVENTO.is_set():
            PULAR_ESPERA_EVENTO.set()
        else:
            REINICIAR_APOS_PARAR.set()
            PARAR_EVENTO.set()
        atualizar_estado(status="Reiniciando...")
        return

    PARAR_EVENTO.clear()
    PARADA_OBRIGATORIA_EVENTO.clear()
    REINICIAR_APOS_PARAR.clear()
    with TABELA_LOCK:
        TABELA_LICITACOES.clear()
    atualizar_estado(status="Reiniciando...", atual="-", total=0, normais=0, favoritas=0, ok=0, falhas=0, revogadas=0)
    print("\n[loop] Robô reiniciado pelo usuário.")
    nova_thread = threading.Thread(target=loop_com_gui, args=(args,), daemon=True)
    THREAD_ROBO["t"] = nova_thread
    nova_thread.start()

def executar_robo(args):
    if args.id:
        ids_monitorados = [{"idCompra": args.id, "uasg": None, "numeroPregao": None, "anoPregao": None, "favorito": False}]
        print(f"[info] Rodando para um unico ID especifico via argumento: {args.id}")
    else:
        ids_monitorados = obter_licitacoes()

    if not ids_monitorados:
        print("[erro] Nenhuma licitacao retornada pela API ou a API esta offline.")
        atualizar_estado(status="Erro: nenhuma licitação retornada pela API.")
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
