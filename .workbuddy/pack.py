import os, sys, zipfile
sys.stdout.reconfigure(encoding="utf-8")
SRC = r"E:\LYY\赣锋锂电遥感解译平台"
OUT = r"E:\LYY\智慧矿山平台-源码包-20261016.zip"
EXCLUDE_DIRS = {"node_modules", "dist", "target", ".venv", "__pycache__", ".git"}
EXCLUDE_SUFFIX = {".class", ".pyc", ".jar"}
count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if os.path.splitext(f)[1] in EXCLUDE_SUFFIX:
                continue
            fp = os.path.join(root, f)
            zf.write(fp, os.path.relpath(fp, SRC))
            count += 1
print(f"files={count} zip={os.path.getsize(OUT)/1024/1024:.1f}MB")
