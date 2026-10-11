"""Serialize native DSS in a persistent main-thread worker on Windows and Linux."""
import json
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
from .errors import RuleError


class Compute:
    def __init__(self): self.process=None; self.queue=None

    def close(self):
        if self.process is not None:
            p=self.process; self.process=None
            if p.poll() is None: p.terminate()
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill();p.wait()
            p.stdin.close();p.stdout.close()

    def call(self,operation,*args):
        if self.process is None or self.process.poll() is not None:
            self.close()
            p=subprocess.Popen([sys.executable,'-u','-m','app.worker'],cwd=Path(__file__).resolve().parent.parent,
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
            self.process=p;self.queue=Queue()
            def read(process,queue):
                try:
                    for line in process.stdout: queue.put(line)
                finally: queue.put(None)
            Thread(target=read,args=(p,self.queue),daemon=True).start()
        try:
            self.process.stdin.write(json.dumps(dict(operation=operation,args=args),allow_nan=False)+'\n')
            self.process.stdin.flush()
            line=self.queue.get(timeout=120)
            if line is None: raise RuntimeError('Native worker exited')
            response=json.loads(line)
        except Exception as exc:
            self.close();raise RuntimeError('Computation worker failed; action was not saved.') from exc
        if not response['ok']:
            if response['type']=='rule': raise RuleError(response['message'])
            raise RuntimeError(response['message'])
        return response['result']
