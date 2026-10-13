"""The browser's seven-day outlook (web/climate.js) must match app/climate.py."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest
from app.climate import outlook, reference

SCRIPT = Path(__file__).resolve().parents[1]/'web'/'climate.js'
CASES = [(42, 0), (7, 96*100+37), (999_999, 96*358), (0, 96*183+95)]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
def test_browser_outlook_matches_python():
    program = (f"const vm=require('vm');vm.runInThisContext(require('fs').readFileSync({json.dumps(str(SCRIPT))},'utf8')+';globalThis.climate=climate;');"
               f"climate.configure({json.dumps(dict(climate=reference()))});"
               f"console.log(JSON.stringify({json.dumps(CASES)}.map(([seed,step])=>climate.outlook(seed,step))));")
    browser = json.loads(subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True).stdout)
    worst = 0.
    for (seed, step), days in zip(CASES, browser):
        expected = outlook(seed, step)
        assert [d['date'] for d in days] == [d['date'] for d in expected]
        for js, py in zip(days, expected):
            for key in ('wind_ms', 'temperature_c', 'solar_kwh_m2', 'daylight_hours'):
                worst = max(worst, abs(js[key]-py[key]))
    assert worst < 1e-9, f'largest browser/Python difference {worst:.3g}'
