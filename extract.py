import re
data=open('api_urls_utf8.txt', encoding='utf-8').read()
urls=re.findall(r'https?://[^\s\'\",]+', data)
for u in urls:
    if 'comprasnet' in u:
        print(u)
