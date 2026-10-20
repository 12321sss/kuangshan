import re,html,sys
def clean(s):
    s=re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>',' ',s)
    s=re.sub(r'(?s)<[^>]+>','\n',s); s=html.unescape(s)
    s=re.sub(r'[ \t]+',' ',s); s=re.sub(r'\n\s*\n+','\n',s)
    return s.strip()
for p in sys.argv[1:]:
    s=open(p,encoding='utf-8',errors='ignore').read()
    m=re.search(r'<title>(.*?)</title>',s,re.S)
    print('#'*95); print('FILE',p,'|',html.unescape(m.group(1)).strip() if m else ''); print('#'*95)
    t=clean(s)
    if '为什么选择阿里云' in t: t=t.split('为什么选择阿里云')[0]
    print(t); print()
