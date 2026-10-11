import json
import sys
import traceback
from . import engine
from .errors import RuleError

for line in sys.stdin:
    try:
        request=json.loads(line)
        func={'create':engine.create,'apply':engine.apply,'public':engine.public,'check_plan':engine.check_plan}[request['operation']]
        result=func(*request['args'])
        reply=dict(ok=True,result=result)
    except RuleError as exc: reply=dict(ok=False,type='rule',message=str(exc))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        reply=dict(ok=False,type='error',message='Physics computation did not complete; action was not saved. Check the server logs.')
    print(json.dumps(reply,allow_nan=False),flush=True)
