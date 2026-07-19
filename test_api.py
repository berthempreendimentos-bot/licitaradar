import time, json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains
options = uc.ChromeOptions()
options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
driver = uc.Chrome(options=options)
driver.get('https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra=16030305900112025')
time.sleep(5)
env = driver.find_element(By.XPATH, '//*[@id="quadroInformativo"]/div[1]/div/div[2]/div/span[5]')
ActionChains(driver).move_to_element(env).click().perform()
time.sleep(5)
logs = driver.get_log('performance')
urls = set()
for log in logs:
    msg = json.loads(log['message'])['message']
    if 'Network.requestWillBeSent' in log['message']:
        urls.add(msg['params'].get('request',{}).get('url'))
for u in urls:
    if 'comprasnet' in str(u) and 'api' in str(u):
        print(u)
driver.quit()
