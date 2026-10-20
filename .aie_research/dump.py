import re,html,urllib.request,sys
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
def txt(i):
    url=f"https://help.aliyun.com/document_detail/{i}.html"
    r=urllib.request.Request(url,headers={"User-Agent":UA})
    s=urllib.request.urlopen(r,timeout=25).read().decode('utf-8','ignore')
    m=re.search(r'<title>(.*?)</title>',s,re.S)
    title=html.unescape(m.group(1)).strip() if m else ''
    # main content region
    mm=re.search(r'(?is)(<div[^>]*(?:id|class)="[^"]*(?:content|article|markdown)[^"]*".*?)(?:<div[^>]*(?:id|class)="[^"]*(?:feedback|helpful))',s)
    body=mm.group(1) if mm else s
    body=re.sub(r'(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>',' ',body)
    body=re.sub(r'(?s)<[^>]+>','\n',body); body=html.unescape(body)
    body=re.sub(r'[ \t]+',' ',body); body=re.sub(r'\n\s*\n+','\n',body)
    return i,title,body.strip()
for i in [int(x) for x in sys.argv[1:]]:
    i,t,b=txt(i)
    print('='*90); print('DOC',i,'|',t); print('='*90); print(b[:6000]); print()
