"""Record exactly the installed runtime/test dependency closure for this package."""
from importlib.metadata import distribution
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pathlib import Path
pending=['fastapi','uvicorn','opendssdirect.py','httpx','pytest']; seen={}
while pending:
    name=canonicalize_name(pending.pop())
    if name in seen:continue
    d=distribution(name);seen[name]=d.version
    for text in d.requires or []:
        r=Requirement(text)
        if r.marker is None or r.marker.evaluate({'extra':''}):pending.append(r.name)
root=Path(__file__).resolve().parents[1]
(root/'requirements.lock').write_text('\n'.join(f'{n}=={v}' for n,v in sorted(seen.items()))+'\n',encoding='utf-8')
print(f'Locked {len(seen)} runtime/test packages')
