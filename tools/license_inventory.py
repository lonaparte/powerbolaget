"""Inventory pinned package licenses, preserve original notices, and record evidence.

Reads only the named requirements/lock files and installed package metadata.
Upstream downloads are pinned license/build documents, with SHA-256 evidence.
"""
from pathlib import Path
from importlib.metadata import distribution
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import hashlib,json,re
import httpx
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent
OUT=ROOT/'licenses';OUT.mkdir(exist_ok=True)

def closure(roots):
    found=set();pending=roots[:]
    while pending:
        n=canonicalize_name(pending.pop())
        if n in found:continue
        found.add(n)
        for raw in distribution(n).requires or []:
            r=Requirement(raw)
            if r.marker is None or r.marker.evaluate({'extra':''}):pending.append(r.name)
    return found

runtime=closure(['fastapi','uvicorn','opendssdirect.py'])
current={canonicalize_name(s.split('==')[0]) for s in (ROOT/'requirements.lock').read_text(encoding='utf-8').splitlines() if '==' in s}
legacy_lock=WORK/'review/powergame/backend/requirements.lock'
legacy={canonicalize_name(s.split('==')[0]) for s in legacy_lock.read_text(encoding='utf-8').splitlines() if '==' in s} if legacy_lock.exists() else set()
overrides={'opendssdirect-py':'LicenseRef-OpenDSSDirect-Alliance-2017','colorama':'BSD-3-Clause',
 'dss-python':'BSD-3-Clause','dss-python-backend':'BSD-3-Clause (wrapper; native components have separate licenses)',
 'numpy':'BSD-3-Clause (plus bundled native licenses)','pandas':'BSD-3-Clause','scipy':'BSD-3-Clause (plus bundled native licenses)',
 'tables':'BSD-3-Clause','patsy':'BSD-2-Clause','python-dateutil':'Apache-2.0 OR BSD-3-Clause',
 'pytz':'MIT','py-cpuinfo':'MIT','pyyaml':'MIT','six':'MIT','h2':'MIT','hpack':'MIT','hyperframe':'MIT'}
packages=[]
for name in sorted(current|legacy):
    d=distribution(name)
    license=overrides.get(name) or d.metadata.get('License-Expression') or d.metadata.get('License')
    if not license:
        for c in d.metadata.get_all('Classifier',[]):
            if 'MIT License' in c:license='MIT'
            if 'BSD License' in c:license='BSD (see original license text)'
    evidence=[]
    for f in d.files or []:
        path=Path(str(f));base=path.name.lower()
        if base.startswith(('license','copying','notice','copyright')) and path.suffix.lower() not in ('.py','.pyc'):
            source=Path(d.locate_file(f))
            if not source.is_file():continue
            dest=(OUT/name/path.name if any(part.endswith('.dist-info') for part in path.parts) else OUT/name/'embedded'/path) if name in current else None
            if dest:
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(source.read_bytes())
            evidence.append(dict(installed_path=str(f),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),copy=str(dest.relative_to(ROOT)) if dest else None))
    packages.append(dict(name=name,version=d.version,scope='current-runtime' if name in runtime else 'current-test-tool' if name in current else 'legacy-only',
                         license=license or 'REVIEW REQUIRED',evidence=evidence,upstream=d.metadata.get_all('Project-URL',[])))
node_lock=WORK/'review/powergame/frontend/package-lock.json'
lock=json.loads(node_lock.read_text(encoding='utf-8')) if node_lock.exists() else {'packages':{}}
node=[dict(name=k.removeprefix('node_modules/'),version=v.get('version'),license=v.get('license'),scope='legacy-frontend-tests') for k,v in lock['packages'].items() if k]
urls={
 'DSS-CAPI-0.14.5-LICENSE.txt':'https://raw.githubusercontent.com/dss-extensions/dss_capi/0.14.5/LICENSE',
 'OpenDSS-EPRI-LICENSE.txt':'https://raw.githubusercontent.com/dss-extensions/dss_capi/0.14.5/OPENDSS_LICENSE',
 'DSS-CAPI-0.14.5-builds.yml':'https://raw.githubusercontent.com/dss-extensions/dss_capi/0.14.5/.github/workflows/builds.yml',
 'KLUSolveX-1.0.0a1-LICENSE.txt':'https://raw.githubusercontent.com/dss-extensions/klusolve/1.0.0a1/LICENSE',
 'KLUSolveX-1.0.0a1-NOTICES.txt':'https://raw.githubusercontent.com/dss-extensions/klusolve/1.0.0a1/README.md',
 'Lazarus-COPYING.LGPL.txt':'https://raw.githubusercontent.com/dss-extensions/dss_capi/0.14.5/src/lazutf8/COPYING.LGPL.txt',
 'Lazarus-COPYING.modifiedLGPL.txt':'https://raw.githubusercontent.com/fpc/Lazarus/lazarus_2_2_0/COPYING.modifiedLGPL.txt',
 'Lazarus-NOTICE.txt':'https://raw.githubusercontent.com/dss-extensions/dss_capi/0.14.5/src/lazutf8/README.md',
}
evidence=[];(OUT/'native').mkdir(exist_ok=True)
for filename,url in urls.items():
    path=OUT/'native'/filename
    if not path.exists():
        r=httpx.get(url,timeout=30,follow_redirects=True);r.raise_for_status();path.write_bytes(r.content)
    content=path.read_bytes()
    evidence.append(dict(file=str(path.relative_to(ROOT)),source=url,sha256=hashlib.sha256(content).hexdigest()))
report=dict(date='2026-10-11',scope='Pinned installed Python distributions, legacy npm lock and declared native dependencies; not a complete binary symbol-level SBOM.',
            project_name='Powerbolaget',project_version='0.0.1',project_license='MIT (included in release; original copyright retained)',current_python_count=len(current),runtime_python_count=len(runtime),python=packages,legacy_node=node,native_evidence=evidence,
            native_components=[
                dict(name='EPRI OpenDSS / DSS C-API',license='BSD-3-Clause',evidence='licenses/native/OpenDSS-EPRI-LICENSE.txt'),
                dict(name='KLUSolveX 1.0.0a1 + KLU/BTF (SuiteSparse 5.6.0)',license='LGPL-2.1-or-later',evidence='DSS C-API 0.14.5 Windows build pins KLUSolveX 1.0.0a1; its README carries component notices'),
                dict(name='AMD / COLAMD',license='BSD-3-Clause',evidence='KLUSolveX-1.0.0a1-NOTICES.txt'),
                dict(name='Eigen 3.3.7',license='MPL-2.0; optional LGPL components depend on build flags',evidence='KLUSolveX-1.0.0a1-NOTICES.txt'),
                dict(name='NumPy Windows wheel: OpenBLAS / LAPACK',license='BSD-3-Clause / BSD-3-Clause-Attribution',evidence='licenses/numpy/LICENSE.txt'),
                dict(name='NumPy Windows wheel: GCC runtime / libquadmath',license='GPL-3.0-or-later WITH GCC-exception-3.1 / LGPL-2.1-or-later',evidence='licenses/numpy/LICENSE.txt'),
                dict(name='NumPy source components',license='BSD-3-Clause, MIT, Zlib; source-only tooling Apache-2.0 and BSD',evidence='licenses/numpy/LICENSE.txt'),
                dict(name='DSS C-API Lazarus UTF8 utilities',license='LGPL-2.0 with Lazarus linking exception (see original texts)',evidence='licenses/native/Lazarus-NOTICE.txt'),
                dict(name='libwinpthread-1.dll',license='MinGW-w64 winpthreads MIT/BSD-style notices; exact wheel build notice not included in wheel metadata',status='binary redistributor must retain exact MinGW runtime notices'),
            ])
(ROOT/'results/license-inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['Powerbolaget 0.0.1 — Third-party license inventory (2026-10-11)',
 'Scope: installed pinned Python packages, the legacy npm lockfile, and reviewed native-library notices. This is not a complete binary-level SBOM.',
 'The frontend uses native HTML / CSS / JavaScript / SVG without a new framework. NASA POWER provides climate calibration data; ORBIT / SAM / NREL reports are methodological references rather than imported libraries.',
 'This source release does not distribute Python, DLLs, .venv, Godot or node_modules. Original license texts are retained below.',
 '', 'Important exceptions:',
 '1. OpenDSSDirect.py 0.9.4 uses a custom Alliance license, not a standard BSD or MIT license. Clause 3 includes corresponding-source publication requirements for research-entity redistribution; clause 4 restricts naming of modified versions. Government rights notices must also be retained. Assess the terms against the actual distribution method.',
 '2. KLUSolveX / KLU / BTF are LGPL-2.1-or-later; Eigen and certifi involve MPL-2.0. The MIT license for original project code does not relicense these files.',
 '3. NumPy Windows wheel notices also include GPL runtime libraries with the GCC Runtime Library Exception and LGPL libquadmath. The top-level NumPy BSD label is not the whole inventory.',
 '4. Any future installer bundling DLLs must document corresponding-source access, replacement/relinking conditions and exact MinGW/Free Pascal runtime versions for the actual binaries. This source release contains no such binaries.',
 '', 'Current Powerbolaget Python packages (runtime / test tools):']
for p in packages:
 if p['scope'].startswith('current'):lines.append(f"{p['name']} {p['version']} | {p['license']} | {p['scope']}")
lines+=['','Retained legacy Python packages (not used by current Powerbolaget):']
for p in packages:
 if p['scope']=='legacy-only':lines.append(f"{p['name']} {p['version']} | {p['license']}")
lines+=['','Legacy Godot 4.4.1: MIT; bundled libraries retain the individual licenses in LICENSES/Godot-COPYRIGHT.txt. Current Powerbolaget does not load Godot.',
 'Legacy frontend jsdom and development dependencies (from package-lock.json):']
for p in node:lines.append(f"{p['name']} {p['version']} | {p['license']}")
lines+=['','Native dependencies:']
for p in report['native_components']:lines.append(f"{p['name']} | {p['license']}")
lines+=['','The project uses MIT and includes its complete LICENSE. Other licensing options are retained here for comparison:',
 'MIT (adopted): permits commercial use, modification and redistribution with copyright and license notices retained. Suitable for open source, learning and further development.',
 'Apache-2.0: consider for new code you can license if contributor patent grants and long-term collaboration matter. It includes explicit patent terms, modification notices and NOTICE obligations; existing MIT notices must remain.',
 'Closed-source / commercial licensing: new code you control may use commercial terms. Existing MIT code and all third-party conditions must still be respected, including the special OpenDSSDirect terms.',
 'GPL-3.0 / AGPL-3.0: consider only if derivative or network-service source disclosure is required. Compatibility with the custom dependency license has not been established; a direct switch is not recommended.',
 'Recommendation: retain MIT for original project code. Before producing a closed-source binary installer, define the distributor and distribution method, consider replacing the OpenDSSDirect wrapper with direct DSS-Python (BSD), and satisfy each native-library condition.',
 '', 'Authoritative texts:',
 'https://opensource.org/license/mit',
 'https://www.apache.org/licenses/LICENSE-2.0',
 'https://raw.githubusercontent.com/dss-extensions/OpenDSSDirect.py/v0.9.4/LICENSE',
 'https://raw.githubusercontent.com/dss-extensions/klusolve/1.0.0a1/README.md',
 'https://www.mozilla.org/en-US/MPL/2.0/FAQ/',
 '', 'Package versions, original license paths, sources and SHA-256 hashes: results/license-inventory.json.']
(ROOT/'LICENSE-REVIEW.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(dict(current=len(current),runtime=len(runtime),legacy=len(legacy-current),node=len(node),unclassified=[p['name'] for p in packages if p['license']=='REVIEW REQUIRED']),ensure_ascii=False))
