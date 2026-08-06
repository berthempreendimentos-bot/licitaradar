import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
import subprocess
import datetime
import os
import re
import json
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Altere esta URL para a sua URL oficial do Vercel quando for fazer o deploy final!
# Exemplo: VERCEL_API = "https://meu-comprasnet.vercel.app"
VERCEL_API = "http://localhost:3001"

INTERVALO_MINUTOS = 5

DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(DIR_ATUAL, "estado_execucao.json")
LOG_FILE = os.path.join(DIR_ATUAL, "log_atualizacoes.log")
HISTORICO_STATUS_FILE = os.path.join(DIR_ATUAL, "historico_status.log")

HORA_INICIO = datetime.datetime.now()
HORA_PARADA = None

estado = {
    "status": "Iniciando...",
    "ultima_atualizacao": "-",
    "varredura_num": 0,
    "total_licitacoes": 0,
    "total_normais": 0,
    "total_favoritas": 0,
    "total_ok": 0,
    "total_falhas": 0,
    "total_revogadas": 0,
    "total_normais_processadas": 0,
    "total_favoritas_processadas": 0,
    "tempo_ativo": "00:00:00",
    "tempo_medio_licitacao": "-",
    "ultimo_tempo_licitacao": "-",
    "_soma_tempo_licitacoes": 0.0,
    "_contador_tempo_licitacoes": 0,
}
estado_lock = threading.Lock()

# Tabela de licitacoes monitoradas: id_compra -> {"label", "status", "horario", "detalhe"}
tabela_licitacoes = {}
tabela_lock = threading.Lock()

stop_event = threading.Event()
pause_event = threading.Event()
parada_obrigatoria_event = threading.Event()
qtd_falhas_parada_obrigatoria = "várias"
processo_atual = None
processo_lock = threading.Lock()


def atualizar_estado(**kwargs):
    with estado_lock:
        estado.update(kwargs)
        estado["ultima_atualizacao"] = datetime.datetime.now().strftime('%H:%M:%S')


def atualizar_tabela(id_compra, status, detalhe="", label=None):
    with tabela_lock:
        existente = tabela_licitacoes.get(id_compra, {})
        tabela_licitacoes[id_compra] = {
            "label": label if label is not None else existente.get("label", id_compra),
            "status": status,
            "horario": datetime.datetime.now().strftime('%H:%M:%S'),
            "detalhe": detalhe,
        }


def carregar_estado_resumo():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return dados.get("ultimo_id_em_processamento")
        except Exception:
            return None
    return None


def salvar_estado_resumo(id_compra):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ultimo_id_em_processamento": id_compra}, f)
    except Exception as e:
        print(f"[aviso] Nao foi possivel salvar o estado de retomada: {e}")


def limpar_estado_resumo():
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except Exception:
            pass


def registrar_historico_status(evento):
    with estado_lock:
        snapshot = {k: v for k, v in estado.items() if not k.startswith("_")}
    registro = {
        "evento": evento,
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **snapshot,
    }
    try:
        with open(HISTORICO_STATUS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[aviso] Nao foi possivel salvar o historico de status: {e}")


def solicitar_parada():
    global HORA_PARADA
    stop_event.set()
    HORA_PARADA = datetime.datetime.now()
    atualizar_estado(status="Parando o robô...")
    registrar_historico_status("parada")
    with processo_lock:
        if processo_atual is not None:
            # taskkill /T mata a arvore inteira de processos (o script e quaisquer
            # processos filhos), garantindo que o pipe de stdout feche na hora e o
            # worker_loop nao fique preso esperando saida do processo antigo.
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(processo_atual.pid)],
                    capture_output=True,
                )
            except Exception:
                try:
                    processo_atual.kill()
                except Exception:
                    pass


def solicitar_pausa():
    pause_event.set()
    atualizar_estado(status="Pausando o robô...")
    registrar_historico_status("pausa")
    with processo_lock:
        if processo_atual is not None:
            # Interrompe a varredura atual do mesmo jeito que o Parar - a licitacao
            # em processamento ja foi salva em estado_execucao.json (salvar_estado_resumo),
            # entao o worker_loop retoma exatamente dai quando a pausa for liberada.
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(processo_atual.pid)],
                    capture_output=True,
                )
            except Exception:
                try:
                    processo_atual.kill()
                except Exception:
                    pass


def solicitar_retomada():
    pause_event.clear()
    atualizar_estado(status="Retomando o robô...")
    registrar_historico_status("retomada")


def _ler_saida_processo(processo, fila):
    try:
        for linha in processo.stdout:
            fila.put(linha)
    except Exception:
        pass
    finally:
        fila.put(None)


def worker_loop():
    global processo_atual

    os.environ["API_BASE_URL"] = VERCEL_API
    varredura = 0
    resume_id = carregar_estado_resumo()
    if resume_id:
        print(f"[loop] Execucao anterior foi interrompida na licitacao ID: {resume_id}. Retomando dai na primeira varredura.")

    while not stop_event.is_set():
        if pause_event.is_set():
            atualizar_estado(status="Robô pausado. Aguardando retomada...")
            while pause_event.is_set() and not stop_event.is_set():
                time.sleep(0.2)
            if stop_event.is_set():
                break
            # Recarrega o ponto de retomada do disco - ele foi salvo pela ultima
            # licitacao em processamento antes da pausa interromper a varredura.
            resume_id = carregar_estado_resumo()
            if resume_id:
                print(f"[loop] Retomando apos pausa na licitacao ID: {resume_id}.")
            continue

        varredura += 1
        atualizar_estado(status=f"Iniciando varredura #{varredura}...", varredura_num=varredura)
        print(f"\n[loop] Iniciando nova varredura ({datetime.datetime.now().strftime('%H:%M:%S')})...")

        comando = [sys.executable, "-u", "monitor_mensagens.py", "--no-wait"]
        if resume_id:
            comando += ["--resume-id", resume_id]

        id_atual = None
        label_atual = None
        try:
            processo = subprocess.Popen(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            with processo_lock:
                processo_atual = processo

            fila_linhas = queue.Queue()
            threading.Thread(target=_ler_saida_processo, args=(processo, fila_linhas), daemon=True).start()

            while not stop_event.is_set():
                try:
                    linha = fila_linhas.get(timeout=0.2)
                except queue.Empty:
                    continue
                if linha is None:
                    break

                linha = linha.rstrip("\n")
                if linha:
                    print(linha)

                match_contagem = re.search(r'Encontradas (\d+) licitacoes normais e (\d+) favoritas', linha)
                if match_contagem:
                    qtd_normais = int(match_contagem.group(1))
                    qtd_favoritas = int(match_contagem.group(2))
                    atualizar_estado(
                        total_normais=qtd_normais,
                        total_favoritas=qtd_favoritas,
                        total_licitacoes=qtd_normais + qtd_favoritas,
                    )
                    continue

                match_lic = re.search(r'Processando Licitacao (\d+) de (\d+) \| ID: (\S+) \| (.+) ---', linha)
                if match_lic:
                    id_atual = match_lic.group(3)
                    label_atual = match_lic.group(4)
                    atualizar_estado(
                        status=f"Processando licitação {match_lic.group(1)}/{match_lic.group(2)} ({label_atual})"
                    )
                    atualizar_tabela(id_atual, "Processando...", "-", label=label_atual)
                    salvar_estado_resumo(id_atual)
                    continue

                if linha.startswith("[ok]") and id_atual:
                    with estado_lock:
                        estado["total_ok"] += 1
                    atualizar_tabela(id_atual, "OK", linha[len("[ok] "):])
                    continue

                if (linha.startswith("[aviso] Falha") or linha.startswith("ERRO:")) and id_atual:
                    with estado_lock:
                        estado["total_falhas"] += 1
                    atualizar_tabela(id_atual, "FALHA", linha)
                    continue

                if linha.startswith("[revogada]") and id_atual:
                    with estado_lock:
                        estado["total_revogadas"] += 1
                    atualizar_tabela(id_atual, "REVOGADA", linha[len("[revogada] "):])
                    continue

                if linha.startswith("[parada_obrigatoria]"):
                    print(f"[loop] PARADA OBRIGATORIA detectada - parando o robô. {linha}")
                    match_qtd = re.search(r'(\d+) falhas consecutivas', linha)
                    global qtd_falhas_parada_obrigatoria
                    qtd_falhas_parada_obrigatoria = match_qtd.group(1) if match_qtd else "várias"
                    atualizar_estado(status="PARADA OBRIGATÓRIA: muitas falhas de pesquisa seguidas.")
                    registrar_historico_status("parada_obrigatoria")
                    parada_obrigatoria_event.set()
                    stop_event.set()
                    continue

                match_tempo = re.search(r'\[tempo\] Licitacao \S+ \((normal|favorita)\) processada em ([\d.]+)s', linha)
                if match_tempo:
                    tipo_tempo = match_tempo.group(1)
                    tempo_gasto = float(match_tempo.group(2))
                    with estado_lock:
                        estado["_soma_tempo_licitacoes"] += tempo_gasto
                        estado["_contador_tempo_licitacoes"] += 1
                        media = estado["_soma_tempo_licitacoes"] / estado["_contador_tempo_licitacoes"]
                        estado["tempo_medio_licitacao"] = f"{media:.1f}s"
                        estado["ultimo_tempo_licitacao"] = f"{tempo_gasto:.1f}s"
                        chave_processadas = "total_normais_processadas" if tipo_tempo == "normal" else "total_favoritas_processadas"
                        estado[chave_processadas] += 1
                    continue

            processo.wait()
            with processo_lock:
                processo_atual = None
            if processo.returncode == 0:
                limpar_estado_resumo()
        except Exception as e:
            atualizar_estado(status=f"Erro na varredura: {e}")
            print(f"[erro] Falha ao executar a varredura: {e}")

        if stop_event.is_set():
            break

        # A retomada so se aplica a primeira varredura apos reiniciar o robo.
        resume_id = None

        atualizar_estado(status="Varredura concluída. Aguardando...")
        print("[loop] Varredura concluída. Iniciando nova varredura em 2 segundos...")
        time.sleep(2)

    if parada_obrigatoria_event.is_set():
        atualizar_estado(status="Robô parado automaticamente (muitas falhas seguidas).")
        print("[loop] Robô parado automaticamente por parada obrigatória.")
    else:
        atualizar_estado(status="Robô parado pelo usuário.")
        print("[loop] Robô parado pelo usuário.")


def baixar_relatorio_erros():
    if not os.path.exists(LOG_FILE):
        messagebox.showinfo("Relatório de Erros", "Nenhum log de execução encontrado ainda.")
        return

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        linhas_erro = [linha for linha in f if "FALHA" in linha]

    if not linhas_erro:
        messagebox.showinfo("Relatório de Erros", "Nenhuma licitação com erro registrada até agora.")
        return

    destino = filedialog.asksaveasfilename(
        title="Salvar relatório de erros",
        defaultextension=".txt",
        initialfile=f"relatorio_erros_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        filetypes=[("Arquivo de texto", "*.txt")],
    )
    if not destino:
        return

    with open(destino, "w", encoding="utf-8") as f:
        f.writelines(linhas_erro)

    messagebox.showinfo(
        "Relatório de Erros",
        f"Relatório salvo com {len(linhas_erro)} ocorrência(s) de erro em:\n{destino}"
    )


def criar_janela():
    root = tk.Tk()
    root.title("Robô ComprasNet - Painel de Status")
    root.geometry("640x790+40+40")
    root.attributes("-topmost", True)
    root.configure(bg="#111827")
    root.resizable(False, False)

    fonte_titulo = ("Segoe UI", 13, "bold")
    fonte_label = ("Segoe UI", 10)
    fonte_valor = ("Consolas", 10, "bold")

    tk.Label(
        root, text="🤖 MÚSCULO DO COMPRASNET\nMODO INFINITO", fg="#22d3ee", bg="#111827",
        font=fonte_titulo, justify="center"
    ).pack(pady=(14, 10))

    frame_botoes = tk.Frame(root, bg="#111827")
    frame_botoes.pack(fill="x", padx=16, pady=(0, 10))

    def ao_clicar_parar():
        if not messagebox.askyesno("Parar Robô", "Tem certeza que deseja parar o robô?\nA varredura atual será interrompida."):
            return
        solicitar_parada()
        btn_parar.config(state="disabled", text="Robô Parado", bg="#4b5563")
        btn_pausar.config(state="disabled", text="⏸ Pausar Robô", bg="#4b5563")

    btn_parar = tk.Button(
        frame_botoes, text="🛑 Parar Robô", bg="#dc2626", fg="white",
        activebackground="#b91c1c", activeforeground="white",
        font=("Segoe UI", 9, "bold"), relief="flat", padx=10, pady=6,
        command=ao_clicar_parar
    )
    btn_parar.pack(side="left", expand=True, fill="x", padx=(0, 6))

    def ao_clicar_pausar():
        if pause_event.is_set():
            solicitar_retomada()
            btn_pausar.config(text="⏸ Pausar Robô", bg="#ca8a04", activebackground="#a16207")
        else:
            solicitar_pausa()
            btn_pausar.config(text="▶ Continuar", bg="#16a34a", activebackground="#15803d")

    btn_pausar = tk.Button(
        frame_botoes, text="⏸ Pausar Robô", bg="#ca8a04", fg="white",
        activebackground="#a16207", activeforeground="white",
        font=("Segoe UI", 9, "bold"), relief="flat", padx=10, pady=6,
        command=ao_clicar_pausar
    )
    btn_pausar.pack(side="left", expand=True, fill="x", padx=(0, 6))

    btn_relatorio = tk.Button(
        frame_botoes, text="📄 Baixar Relatório de Erros", bg="#374151", fg="white",
        activebackground="#4b5563", activeforeground="white",
        font=("Segoe UI", 9, "bold"), relief="flat", padx=10, pady=6,
        command=baixar_relatorio_erros
    )
    btn_relatorio.pack(side="left", expand=True, fill="x", padx=(6, 0))

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
    lbl_ultima_atualizacao = linha("Última atualização:")
    lbl_varredura = linha("Varredura nº:")
    lbl_total = linha("Licitações monitoradas:")
    lbl_normais = linha("— Normais:")
    lbl_favoritas = linha("— ★ Favoritas:")
    lbl_ok = linha("Total OK:")
    lbl_falhas = linha("Total falhas:")
    lbl_revogadas = linha("Revogadas (auto):")
    lbl_tempo_ativo = linha("Tempo em funcionamento:")
    lbl_tempo_medio = linha("Tempo médio/licitação:")
    lbl_ultimo_tempo = linha("Última licitação:")
    lbl_normais_processadas = linha("— Normais monitoradas:")
    lbl_favoritas_processadas = linha("— ★ Favoritas monitoradas:")

    tk.Label(
        root, text="Licitações monitoradas nesta varredura",
        fg="#9ca3af", bg="#111827", font=fonte_label, anchor="w"
    ).pack(fill="x", padx=16, pady=(12, 4))

    frame_tabela = tk.Frame(root, bg="#111827")
    frame_tabela.pack(fill="both", expand=True, padx=16, pady=(0, 12))

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
    tabela = ttk.Treeview(frame_tabela, columns=colunas, show="headings", height=11)
    tabela.heading("id", text="Licitação")
    tabela.heading("status", text="Status")
    tabela.heading("horario", text="Horário")
    tabela.heading("detalhe", text="Detalhe")
    tabela.column("id", width=190, anchor="w")
    tabela.column("status", width=90, anchor="center")
    tabela.column("horario", width=70, anchor="center")
    tabela.column("detalhe", width=170, anchor="w")

    scrollbar = ttk.Scrollbar(frame_tabela, orient="vertical", command=tabela.yview)
    tabela.configure(yscrollcommand=scrollbar.set)
    tabela.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    tabela.tag_configure("ok", foreground="#4ade80")
    tabela.tag_configure("falha", foreground="#f87171")
    tabela.tag_configure("processando", foreground="#facc15")
    tabela.tag_configure("revogada", foreground="#fb923c")

    def atualizar_gui():
        with estado_lock:
            lbl_status.config(text=estado["status"])
            lbl_ultima_atualizacao.config(text=estado["ultima_atualizacao"])
            lbl_varredura.config(text=str(estado["varredura_num"]))
            lbl_total.config(text=str(estado["total_licitacoes"]))
            lbl_normais.config(text=str(estado["total_normais"]))
            lbl_favoritas.config(text=str(estado["total_favoritas"]))
            lbl_ok.config(text=str(estado["total_ok"]))
            lbl_falhas.config(text=str(estado["total_falhas"]))
            lbl_revogadas.config(text=str(estado["total_revogadas"]))
            lbl_tempo_medio.config(text=estado["tempo_medio_licitacao"])
            lbl_ultimo_tempo.config(text=estado["ultimo_tempo_licitacao"])
            lbl_normais_processadas.config(text=str(estado["total_normais_processadas"]))
            lbl_favoritas_processadas.config(text=str(estado["total_favoritas_processadas"]))

        if parada_obrigatoria_event.is_set():
            parada_obrigatoria_event.clear()
            messagebox.showwarning(
                "Parada obrigatória",
                f"O robô parou automaticamente após {qtd_falhas_parada_obrigatoria} falhas de pesquisa seguidas.\n\n"
                "Isso costuma indicar um problema sistêmico (Chrome fechado, posição do botão "
                "'Mensagens' mudou, ou o site do ComprasNet mudou de layout).\n\n"
                "Verifique antes de reiniciar o robô."
            )

        fim_contagem = HORA_PARADA if HORA_PARADA else datetime.datetime.now()
        decorrido = fim_contagem - HORA_INICIO
        total_segundos = int(decorrido.total_seconds())
        horas, resto = divmod(total_segundos, 3600)
        minutos, segundos = divmod(resto, 60)
        lbl_tempo_ativo.config(text=f"{horas:02d}:{minutos:02d}:{segundos:02d}")

        with tabela_lock:
            copia = dict(tabela_licitacoes)

        existentes = set(tabela.get_children())
        for id_compra, info in copia.items():
            tag = {"OK": "ok", "FALHA": "falha", "Processando...": "processando", "REVOGADA": "revogada"}.get(info["status"], "")
            valores = (info["label"], info["status"], info["horario"], info["detalhe"])
            if id_compra in existentes:
                tabela.item(id_compra, values=valores, tags=(tag,))
            else:
                tabela.insert("", "end", iid=id_compra, values=valores, tags=(tag,))

        # Mantem as licitacoes em analise sempre no topo da tabela.
        em_analise = [id_c for id_c, info in copia.items() if info["status"] == "Processando..."]
        for posicao, id_c in enumerate(em_analise):
            tabela.move(id_c, "", posicao)

        if stop_event.is_set():
            btn_parar.config(state="disabled", text="Robô Parado", bg="#4b5563")
            btn_pausar.config(state="disabled", text="⏸ Pausar Robô", bg="#4b5563")
        else:
            # Reforça o "sempre visível" caso outra janela (ex.: Chrome) tente sobrepor.
            root.attributes("-topmost", True)

        root.after(500, atualizar_gui)

    def ao_fechar_janela():
        if not stop_event.is_set():
            solicitar_parada()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", ao_fechar_janela)

    atualizar_gui()
    root.mainloop()


def main():
    print("=" * 60)
    print("🤖 MÚSCULO DO COMPRASNET - MODO INFINITO 🤖")
    print("=" * 60)
    print(f"Alvo da API: {VERCEL_API}")
    print("Intervalo de varredura: Contínuo (imediato).")
    print("Este terminal deve permanecer aberto para puxar ordens da nuvem.")
    print("Uma janela de status foi aberta e ficará sempre visível na tela.")
    print("=" * 60)

    registrar_historico_status("inicio")

    thread_worker = threading.Thread(target=worker_loop, daemon=True)
    thread_worker.start()

    criar_janela()


if __name__ == "__main__":
    main()
