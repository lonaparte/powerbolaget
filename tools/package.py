"""Create a clean upload folder containing source, evidence and license texts."""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
version = next(ast.literal_eval(node.value)
               for node in ast.parse((root / 'app/parameters.py').read_text(encoding='utf-8')).body
               if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root.parent / f'Powerbolaget-{version}')
destination = parser.parse_args().output.resolve()
if destination == root or root in destination.parents:
    raise SystemExit('Choose a new output folder outside the source directory.')
destination.mkdir(parents=True, exist_ok=False)

folders = ['app', 'web', 'docs', 'tests', 'tools', 'screenshots', 'examples', 'results', 'licenses']
files = ['README.md', 'LICENSE', 'Dockerfile', 'compose.yaml', '.dockerignore',
         'run.py', 'requirements.lock', 'pyproject.toml', 'pytest.ini',
         'LICENSE-REVIEW.txt', 'THIRD-PARTY-NOTICES.txt', 'DEVELOPMENT-TREE.txt']
for name in files:
    shutil.copy2(root / name, destination / name)
for folder in folders:
    for source in (root / folder).rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts and source.suffix != '.pyc':
            target = destination / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

subprocess.run([sys.executable, str(destination / 'tools/development_tree.py'), '--project-only'], check=True)
assert (destination / 'LICENSE').read_bytes() == (root / 'LICENSE').read_bytes()
assert (destination / 'THIRD-PARTY-NOTICES.txt').is_file()
assert not any(p.name.lower() == '.git' for p in destination.rglob('*'))
print(destination)
print(f'{sum(p.is_file() for p in destination.rglob("*"))} files; no archive created.')
