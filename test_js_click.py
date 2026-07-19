import undetected_chromedriver as uc
import time
driver = uc.Chrome(headless=False)
driver.set_window_rect(x=0, y=0, width=1366, height=768)
driver.get('https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra=92589905900242025')
time.sleep(10)
driver.execute_script('document.elementFromPoint(1259, 310).click();')
time.sleep(5)
text = driver.execute_script('return document.body.innerText;')
print('MENSAGEM ENCONTRADA' if 'Mensagem do Sistema' in text or 'Mensagens' in text else 'FALHOU')
open('debug_text.txt', 'w', encoding='utf-8').write(text)
driver.quit()
