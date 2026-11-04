"""List project development files while collapsing dependencies, caches and saves."""
from datetime import date
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
VERSION=re.search(r"__version__ = '([^']+)'",(ROOT/'app/__init__.py').read_text(encoding='utf-8')).group(1)
OUT=ROOT/'DEVELOPMENT-TREE.txt';OUT.touch(exist_ok=True)
COLLAPSE={'.venv':'Third-party Python environment','.pnpm-store':'Package cache','node_modules':'Third-party npm packages',
          '.git':'Git metadata','.godot':'Godot import cache','data':'Runtime saves','backups':'User-save backups',
          'qa-data':'Legacy test runtime data','qa-pytest-temp':'Test temporary files'}
SKIP={'__pycache__','.pytest_cache','.tmp','.git'}
def entries(folder):
    return sorted([p for p in folder.iterdir() if p.name not in SKIP and not p.name.startswith(('.test-tmp','pytest-cache-files'))],key=lambda p:(not p.is_dir(),p.name.lower()))
def tree(folder,prefix=''):
    rows=[];items=entries(folder)
    for i,p in enumerate(items):
        last=i==len(items)-1;stem='└── ' if last else '├── '
        note=COLLAPSE.get(p.name)
        rows.append(prefix+stem+p.name+('/' if p.is_dir() else '')+(f'  [{note}; collapsed]' if note else ''))
        if p.is_dir() and not note:rows.extend(tree(p,prefix+('    ' if last else '│   ')))
    return rows
project_only='--project-only' in sys.argv
rows=[f'Powerbolaget {VERSION} development tree / {date.today().isoformat()}','Project root: .' if project_only else f'Current source directory: {ROOT}',
      'Lists source, tests, configuration, documentation, results and license evidence.',
      'Collapses installed dependencies and runtime data; ignores Python, pytest and tool caches.',
      '',(f'Powerbolaget-{VERSION}' if project_only else ROOT.name)+'/']
rows.extend(tree(ROOT))
if project_only:
    OUT.write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print(f'{OUT}: {len(rows)} lines')
    raise SystemExit(0)
legacy=ROOT.parent/'review/powergame'
if legacy.exists():
    rows+=['','Retained original version (separate from current source):','review/powergame/'];rows.extend(tree(legacy))
rows+=['','Other workspace development/validation files:']
for name in ['audit_release.py','qa_windows.py','test-results.json','test-report.txt','final-save.json','screenshots']+sorted(p.name for p in ROOT.parent.glob('*.zip')):
    path=ROOT.parent/name
    if path.exists():
        rows.append(name+('/' if path.is_dir() else ''))
        if path.is_dir():rows.extend(tree(path))
OUT.write_text('\n'.join(rows)+'\n',encoding='utf-8')
print(f'{OUT}: {len(rows)} lines')
