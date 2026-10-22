"""Refresh the tracked + untracked, non-ignored project snapshot inventory."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
items=[]
for name in sorted(set(files)-{'','backup_manifest.json'}):
    p=ROOT/name
    if p.is_symlink():items.append({'path':name,'symlink':str(p.readlink())})
    elif p.is_file():
        with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
        items.append({'path':name,'bytes':p.stat().st_size,'sha256':sha})
(ROOT/'backup_manifest.json').write_text(json.dumps({'scope':'All non-ignored project files; manifest itself excluded from hashes','files':items},ensure_ascii=False,indent=2)+'\n')
print('Inventory:',len(items),'files')
