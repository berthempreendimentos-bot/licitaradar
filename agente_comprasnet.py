# -*- coding: utf-8 -*-
"""
AGENTE COMPRASNET — automação com mouse e teclado (estilo Cowork)
=================================================================
Abre o Chrome, acessa a página pública de compras do ComprasNet,
digita como uma pessoa, copia o conteúdo da página e salva o
resultado em arquivo de texto + captura de tela.

INSTALAÇÃO (uma vez só):
    pip install pyautogui pyperclip pillow

USO:
    python agente_comprasnet.py                      -> só abre e captura a página
    python agente_comprasnet.py "material hospitalar" -> pesquisa o termo antes de capturar

DICA: para descobrir coordenadas de um botão/campo na sua tela:
    python agente_comprasnet.py --coordenadas
    (mova o mouse até o local desejado e veja X,Y no terminal)
"""

import sys
import time
import subprocess
import datetime

import pyautogui
import pyperclip

# ----------------------- CONFIGURAÇÕES -----------------------
URL = "https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras"

TEMPO_CARREGAR_CHROME = 5      # segundos esperando o Chrome abrir
TEMPO_CARREGAR_PAGINA = 15     # segundos esperando a página carregar (é um site lento/Angular)
TEMPO_APOS_PESQUISA   = 10     # segundos esperando o resultado da pesquisa

# Coordenada do campo de pesquisa da página (ajuste com --coordenadas se precisar)
# None = usa TAB para navegar até o campo em vez de clicar
CAMPO_PESQUISA_XY = None       # exemplo: (640, 320)

VELOCIDADE_DIGITACAO = 0.05    # segundos entre teclas (parece digitação humana)

pyautogui.FAILSAFE = True      # jogue o mouse no canto sup. esquerdo p/ abortar
pyautogui.PAUSE = 0.4          # pausa padrão entre ações
# --------------------------------------------------------------


def abrir_chrome():
    """Abre o Chrome em uma janela nova."""
    if sys.platform.startswith("win"):
        subprocess.Popen(["cmd", "/c", "start", "chrome", "--new-window", "about:blank"], shell=False)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-na", "Google Chrome", "--args", "--new-window", "about:blank"])
    else:
        subprocess.Popen(["google-chrome", "--new-window", "about:blank"])
    time.sleep(TEMPO_CARREGAR_CHROME)


def navegar(url):
    """Clica na barra de endereço (Ctrl+L), digita a URL e dá Enter."""
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)
    pyautogui.typewrite(url, interval=0.02)
    pyautogui.press("enter")
    print(f"[agente] Acessando {url} ...")
    time.sleep(TEMPO_CARREGAR_PAGINA)


def pesquisar(termo):
    """Localiza o campo de pesquisa e digita o termo como uma pessoa."""
    if CAMPO_PESQUISA_XY:
        x, y = CAMPO_PESQUISA_XY
        pyautogui.moveTo(x, y, duration=0.8)   # movimento suave do mouse
        pyautogui.click()
    else:
        # Sem coordenada definida: navega por TAB até o primeiro campo de texto
        pyautogui.click(pyautogui.size().width // 2, 200)  # foca a página
        for _ in range(3):
            pyautogui.press("tab")
            time.sleep(0.3)
    time.sleep(0.5)
    pyautogui.typewrite(termo, interval=VELOCIDADE_DIGITACAO)
    pyautogui.press("enter")
    print(f"[agente] Pesquisando: {termo}")
    time.sleep(TEMPO_APOS_PESQUISA)


def rolar_pagina(vezes=3):
    """Rola a página para carregar mais resultados."""
    for _ in range(vezes):
        pyautogui.scroll(-600)
        time.sleep(1)


def capturar_resultado():
    """Seleciona tudo (Ctrl+A), copia (Ctrl+C) e retorna o texto da página."""
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(1)
    pyautogui.press("escape")  # desfaz a seleção
    return pyperclip.paste()


def salvar(texto):
    """Salva texto e screenshot com data/hora no nome."""
    carimbo = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    arquivo_txt = f"resultado_comprasnet_{carimbo}.txt"
    with open(arquivo_txt, "w", encoding="utf-8") as f:
        f.write(texto)

    arquivo_png = f"tela_comprasnet_{carimbo}.png"
    pyautogui.screenshot(arquivo_png)

    print(f"[agente] Texto salvo em:  {arquivo_txt}")
    print(f"[agente] Tela salva em:  {arquivo_png}")


def modo_coordenadas():
    """Mostra a posição do mouse em tempo real (Ctrl+C para sair)."""
    print("Mova o mouse até o campo/botão desejado. Ctrl+C para sair.\n")
    try:
        while True:
            p = pyautogui.position()
            print(f"\rX={p.x:4d}  Y={p.y:4d}", end="")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nAnote as coordenadas e coloque em CAMPO_PESQUISA_XY no script.")


def main():
    if "--coordenadas" in sys.argv:
        modo_coordenadas()
        return

    termo = " ".join(a for a in sys.argv[1:] if not a.startswith("--")).strip()

    print("[agente] Iniciando... NÃO use o mouse/teclado durante a execução.")
    print("[agente] Para abortar, jogue o mouse no canto superior esquerdo da tela.\n")

    abrir_chrome()
    navegar(URL)

    if termo:
        pesquisar(termo)

    rolar_pagina()
    texto = capturar_resultado()

    if texto.strip():
        salvar(texto)
        print(f"\n[agente] Concluído! {len(texto)} caracteres capturados.")
    else:
        print("\n[agente] Nada foi copiado — a página pode não ter terminado de carregar.")
        print("         Aumente TEMPO_CARREGAR_PAGINA no topo do script e tente de novo.")


if __name__ == "__main__":
    main()
