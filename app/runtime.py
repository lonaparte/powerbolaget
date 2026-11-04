"""Simulation worker processes.

The power-flow engine (OpenDSS) only works from the thread that created its contexts, and the web
server serves requests from a thread pool. Worlds therefore live in worker processes whose main thread
runs every world operation; the web process never loads the engine. Sessions are spread over
POWERBOLAGET_WORKERS processes (default 1), each using one CPU core. If a worker dies, its sessions
are gone and the players' browsers bring their games back from their own saves.
"""
import multiprocessing as mp
import os
import threading
import traceback


class Gone(Exception):
    """The session does not exist in this worker (expired, evicted or the worker restarted)."""


class Rejected(Exception):
    """A request the model refused (invalid build, command or save)."""


def worker(conn):
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    from . import views
    from .construction import BuildError
    from .saves import SaveError
    from .world import CommandError, World, command, plan_build
    worlds = {}

    def need(sid):
        w = worlds.get(sid)
        if w is None:
            raise Gone()
        return w

    def tick(w, a):
        w.advance(a['minutes'], budget_s=a['budget'])
        out = dict(snapshot=views.snapshot(w, a['since_log']))
        if a['grid_version'] != w.grid['version'] or a['firm_count'] != len(w.firms):
            out['static'] = views.static(w)
        return out

    def cmd(w, a):
        message = command(w, a['command'])
        w.solve_now(float(w.minute))
        return dict(message=message, snapshot=views.snapshot(w, a['since_log']), static=views.static(w))

    def preview(w, a):
        try:
            plan = plan_build(w, dict(a['build']))
        except BuildError as exc:
            return dict(ok=False, error=str(exc))
        return dict(ok=True, plan={k: v for k, v in plan.items() if k != 'connect_bus'})

    ops = dict(
        tick=tick, command=cmd, preview=preview, save=lambda w, a: w.state(),
        entity=lambda w, a: views.entity(w, a['id']), table=lambda w, a: views.table(w, a['name']),
        parcel=lambda w, a: views.parcel(w, a['x'], a['y']))
    while True:
        try:
            op, sid, args = conn.recv()
        except (EOFError, KeyboardInterrupt):
            break
        try:
            if op == 'stop':
                conn.send(('ok', None))
                break
            if op in ('new', 'load'):
                w = World(seed=args['seed']) if op == 'new' else World(state=args['state'])
                worlds[sid] = w
                result = dict(static=views.static(w), snapshot=views.snapshot(w))
            elif op == 'drop':
                worlds.pop(sid, None)
                result = None
            else:
                result = ops[op](need(sid), args)
            conn.send(('ok', result))
        except Gone:
            conn.send(('gone', None))
        except (CommandError, BuildError, SaveError) as exc:
            conn.send(('rejected', str(exc)))
        except Exception:
            conn.send(('failed', traceback.format_exc()))
    worlds.clear()


class Worker:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.conn = None
        self.generation = 0

    def start(self):
        ctx = mp.get_context('spawn')
        here, there = ctx.Pipe()
        self.proc = ctx.Process(target=worker, args=(there,), name='powerbolaget-world', daemon=True)
        self.proc.start()
        there.close()
        self.conn = here
        self.generation += 1

    def call(self, op, sid, args, timeout=120):
        with self.lock:
            if self.proc is None or not self.proc.is_alive():
                self.start()
            try:
                self.conn.send((op, sid, args))
                if not self.conn.poll(timeout):
                    raise TimeoutError('The simulation did not answer in time.')
                status, value = self.conn.recv()
            except (EOFError, BrokenPipeError, OSError, TimeoutError):
                self.kill()
                raise Gone()
        if status == 'ok':
            return value
        if status == 'gone':
            raise Gone()
        if status == 'rejected':
            raise Rejected(value)
        raise RuntimeError(value)

    def kill(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.join(5)
        self.proc = None

    def stop(self):
        if self.proc is not None and self.proc.is_alive():
            try:
                with self.lock:
                    self.conn.send(('stop', None, None))
                    self.conn.poll(10)
            except (OSError, EOFError):
                pass
            self.proc.join(10)
        self.kill()
