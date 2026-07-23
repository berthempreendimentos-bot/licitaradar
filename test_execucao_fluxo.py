# -*- coding: utf-8 -*-
"""
Script de teste de execução do fluxo completo.
Mocks do PyAutoGUI, Pyperclip e subprocess para permitir a execução completa e limpa no terminal,
enviando dados de teste reais para a API local (http://localhost:3001).
"""

import sys
import os
import json
import urllib.request
from unittest.mock import patch, MagicMock

# Adiciona o diretório atual ao path para importação
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Dados simulados copiados da tela do ComprasNet
MOCK_TEXTO_CHAT = """
Mensagem do Pregoeiro
Senhores licitantes, bom dia. Vamos dar início à sessão pública.
21/07/2026 13:00

Mensagem do Sistema
O fornecedor de menor valor foi convocado para envio de anexos.
21/07/2026 13:05
"""

def testar_fluxo():
    print("=" * 60)
    print("🧪 INICIANDO TESTE DE EXECUÇÃO DO FLUXO COMPLETO 🧪")
    print("=" * 60)
    
    # 1. Obter a primeira licitação ativa da API local para usar no teste
    try:
        url_monitorados = "http://localhost:3001/api/monitorados"
        print(f"[teste] Obtendo licitações de: {url_monitorados} ...")
        res = urllib.request.urlopen(url_monitorados)
        dados = json.loads(res.read().decode('utf-8'))
        itens = dados.get("itens", [])
        if not itens:
            print("[erro] Nenhuma licitação cadastrada para testar. Cadastre uma UASG no painel primeiro!")
            return False
        id_compra_teste = itens[0]["idCompra"]
        print(f"[teste] Usando idCompra de teste: {id_compra_teste}")
    except Exception as e:
        print(f"[erro] Não foi possível conectar à API local: {e}")
        print("Certifique-se de que o servidor Node.js está rodando na porta 3001.")
        return False

    # 2. Criar arquivo temporário de posição do botão para não bloquear no input de calibração
    caminho_posicao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posicao_botao.json")
    posicao_criada = False
    if not os.path.exists(caminho_posicao):
        print("[teste] Criando arquivo posicao_botao.json temporário para evitar bloqueio interativo...")
        with open(caminho_posicao, 'w') as f:
            json.dump({"x": 100, "y": 100}, f)
        posicao_criada = True

    # 3. Aplicar mocks e rodar o fluxo principal do monitor_mensagens
    print("[teste] Aplicando mocks em pyautogui, pyperclip, msvcrt e subprocess...")
    
    mock_pyautogui = MagicMock()
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = MOCK_TEXTO_CHAT
    
    mock_msvcrt = MagicMock()
    mock_msvcrt.kbhit.return_value = True
    mock_msvcrt.getwch.return_value = '\r' # Simula o ENTER para usar coordenadas salvas imediatamente

    # Patch nos imports e execução de comandos do Chrome
    with patch.dict('sys.modules', {'pyautogui': mock_pyautogui, 'pyperclip': mock_pyperclip, 'msvcrt': mock_msvcrt}), \
         patch('subprocess.run') as mock_sub_run, \
         patch('sys.argv', ['monitor_mensagens.py', '--id', id_compra_teste]):

        
        # Importa monitor_mensagens sob a árvore com patches aplicados
        import monitor_mensagens
        
        print("[teste] Executando monitor_mensagens.main()...")
        try:
            monitor_mensagens.main()
            print("[teste] Execução do fluxo concluída!")
            fluxo_ok = True
        except Exception as err:
            print(f"[erro] Falha durante execução do fluxo: {err}")
            fluxo_ok = False

    # 4. Limpar o arquivo temporário de calibração criado
    if posicao_criada and os.path.exists(caminho_posicao):
        try:
            os.remove(caminho_posicao)
            print("[teste] Arquivo temporário posicao_botao.json removido.")
        except:
            pass

    return fluxo_ok

if __name__ == "__main__":
    sucesso = testar_fluxo()
    sys.exit(0 if sucesso else 1)
