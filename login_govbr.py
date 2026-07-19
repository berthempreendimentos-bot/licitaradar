import undetected_chromedriver as uc
import os

def main():
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_profile")
    print(f"Usando perfil isolado do bot em: {profile_path}")

    options = uc.ChromeOptions()
    options.headless = False
    options.add_argument(f'--user-data-dir={profile_path}')
    options.add_argument('--window-position=0,0') # GARANTE QUE ABRIRA NA TELA PRINCIPAL

    print("Iniciando Chrome do Bot...")
    try:
        driver = uc.Chrome(options=options)
        # Acessar uma licitação específica garante que a página carregue corretamente para o login
        driver.get("https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra=15311505900102026")

        print("\n" + "="*70)
        print("POR FAVOR, FACA O LOGIN NO GOV.BR NO NAVEGADOR QUE SE ABRIU.")
        print("Quando terminar e ver a tela do comprasnet logada, aperte ENTER aqui no terminal.")
        print("="*70 + "\n")

        input("Aperte ENTER para fechar e salvar o perfil...")

        driver.quit()
        print("Perfil salvo com sucesso! Agora o bot pode rodar invisivel de forma independente.")
    except Exception as e:
        print(f"Erro ao iniciar Chrome: {e}")
        print("Certifique-se de que o bot principal nao esta rodando no momento.")

if __name__ == "__main__":
    main()
