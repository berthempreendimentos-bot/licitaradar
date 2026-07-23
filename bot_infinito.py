import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
import subprocess
import datetime
import os

# Altere esta URL para a sua URL oficial do Vercel quando for fazer o deploy final!
# Exemplo: VERCEL_API = "https://meu-comprasnet.vercel.app"
VERCEL_API = "http://localhost:3001" 

INTERVALO_MINUTOS = 5

def main():
    print("=" * 60)
    print("🤖 MÚSCULO DO COMPRASNET - MODO INFINITO 🤖")
    print("=" * 60)
    print(f"Alvo da API: {VERCEL_API}")
    print("Intervalo de varredura: Contínuo (imediato).")
    print("Este terminal deve permanecer aberto para puxar ordens da nuvem.")
    print("=" * 60)

    os.environ["API_BASE_URL"] = VERCEL_API

    while True:
        print(f"\n[loop] Iniciando nova varredura ({datetime.datetime.now().strftime('%H:%M:%S')})...")
        
        # Chama o monitor_mensagens.py usando o mesmo interpretador executando o bot_infinito.py
        subprocess.run([sys.executable, "monitor_mensagens.py", "--no-wait"])
        
        print("[loop] Varredura concluída. Iniciando nova varredura em 2 segundos...")
        time.sleep(2)

if __name__ == "__main__":
    main()
