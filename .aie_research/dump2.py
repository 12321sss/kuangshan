import re,html,urllib.request,sys
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
def clean(s):
    s=re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>',' ',s)
    s=re.sub(r'(?s)<[^>]+>','\n',s); s=html.unescape(s)
    s=re.sub(r'[ \t]+',' ',s); s=re.sub(r'\n\s*\n+','\n',s)
    return s.strip()
def get(i):
    url=f"https://help.aliyun.com/document_detail/{i}.html"
    r=urllib.request.Request(url,headers={"User-Agent":UA})
    s=urllib.request.urlopen(r,timeout=25).read().decode('utf-8','ignore')
    m=re.search(r'<title>(.*?)</title>',s,re.S)
    title=html.unescape(m.group(1)).strip() if m else ''
    t=clean(s)
    # cut footer boilerplate
    for cut in ['为什么选择阿里云','为什么选择阿里云']:
        if cut in t: t=t.split(cut)[0]
    return i,title,t
for i in [int(x) for x in sys.argv[1:]]:
    i,ti,b=get(i)
    print('#'*95); print(f'DOC {i} | {ti}'); print('#'*95); print(b); print()
