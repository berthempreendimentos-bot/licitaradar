# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import urllib.error

# Garante que podemos importar monitor_mensagens
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import monitor_mensagens

class TestMonitorMensagens(unittest.TestCase):
    
    def test_extrair_mensagens_padrao(self):
        """Testa a extração de mensagens com formato padrão (com data e remetente)."""
        texto_bruto = (
            "Mensagem do Pregoeiro\n"
            "Senhores licitantes, bom dia.\n"
            "21/07/2026 10:00\n"
            "\n"
            "Mensagem do Sistema\n"
            "O item 1 foi homologado.\n"
            "21/07/2026 10:05\n"
        )
        resultado = monitor_mensagens.extrair_mensagens(texto_bruto)
        
        esperado_1 = "Mensagem do Pregoeiro\nSenhores licitantes, bom dia.\n21/07/2026 10:00"
        esperado_2 = "Mensagem do Sistema\nO item 1 foi homologado.\n21/07/2026 10:05"
        
        self.assertIn(esperado_1, resultado)
        self.assertIn(esperado_2, resultado)

    def test_extrair_mensagens_sem_prefixo(self):
        """Testa se mensagens sem 'Mensagem do/a' recebem o prefixo 'Mensagem do Sistema'."""
        texto_bruto = (
            "Instabilidade detectada no portal.\n"
            "21/07/2026 10:10\n"
        )
        resultado = monitor_mensagens.extrair_mensagens(texto_bruto)
        
        esperado = "Mensagem do Sistema\nInstabilidade detectada no portal.\n21/07/2026 10:10"
        self.assertEqual(resultado, esperado)

    def test_extrair_mensagens_com_linhas_em_branco(self):
        """Testa a tolerância a linhas vazias e espaços em branco."""
        texto_bruto = (
            "  Mensagem do Sistema  \n"
            "\n"
            "  Abertura da disputa.  \n"
            "\n"
            "21/07/2026 10:15\n"
        )
        resultado = monitor_mensagens.extrair_mensagens(texto_bruto)
        esperado = "Mensagem do Sistema\nAbertura da disputa.\n21/07/2026 10:15"
        self.assertEqual(resultado, esperado)

    @patch('urllib.request.urlopen')
    def test_obter_licitacoes_mock_sucesso(self, mock_urlopen):
        """Testa obter_licitacoes simulando um retorno de sucesso da API."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"itens": [{"idCompra": "12345"}, {"idCompra": "67890"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        resultado = monitor_mensagens.obter_licitacoes()
        self.assertEqual(resultado, ["12345", "67890"])

    @patch('urllib.request.urlopen')
    def test_obter_licitacoes_mock_erro(self, mock_urlopen):
        """Testa obter_licitacoes tratando erros de requisição HTTP."""
        mock_urlopen.side_effect = Exception("Erro de conexão")
        
        resultado = monitor_mensagens.obter_licitacoes()
        self.assertEqual(resultado, [])

    @patch('urllib.request.urlopen')
    def test_enviar_para_api_mock_sucesso(self, mock_urlopen):
        """Testa o envio de mensagens para a API simulando sucesso."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true, "total": 1, "novas": 1}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        resultado = monitor_mensagens.enviar_para_api("Mensagem de Teste", "12345")
        self.assertIsNotNone(resultado)
        self.assertTrue(resultado.get("ok"))

    @patch('urllib.request.urlopen')
    def test_enviar_para_api_mock_erro_http(self, mock_urlopen):
        """Testa o envio de mensagens para a API simulando erro HTTP 500."""
        # Criar mock do HTTPError
        fp_mock = MagicMock()
        fp_mock.read.return_value = b'{"erro": "Internal Error"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://localhost:3001/api/mensagens/12345",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=fp_mock
        )

        resultado = monitor_mensagens.enviar_para_api("Mensagem de Teste", "12345")
        self.assertIsNone(resultado)

    def test_integracao_api_local(self):
        """Teste de integração real com a API local se ela estiver ativa."""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect(("127.0.0.1", 3001))
            s.close()
            api_online = True
        except:
            api_online = False
            
        if not api_online:
            self.skipTest("API local em http://localhost:3001 offline. Pulando teste de integração.")
            
        print("\n[Integração] Executando chamada real para API local ativa...")
        resultado = monitor_mensagens.obter_licitacoes()
        self.assertIsInstance(resultado, list)
        print(f"[Integração] Encontradas {len(resultado)} licitações monitoradas.")

if __name__ == '__main__':
    unittest.main()
