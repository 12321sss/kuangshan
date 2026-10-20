import re,html,urllib.request,concurrent.futures
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
def get(i):
    url=f"https://help.aliyun.com/document_detail/{i}.html"
    try:
        r=urllib.request.Request(url,headers={"User-Agent":UA})
        s=urllib.request.urlopen(r,timeout=20).read().decode('utf-8','ignore')
        m=re.search(r'<title>(.*?)</title>',s,re.S)
        t=html.unescape(m.group(1)).strip() if m else ''
        return i,t
    except Exception as e:
        return i,'ERR'
ids=list(range(128280,128360))
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    for i,t in ex.map(get,ids):
        if 'AI Earth' in t or '数知地球' in t or '遥感影像分析' in t:
            print(i,'|',t)
