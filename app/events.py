"""Event queue of the World Simulation Core.

Events carry a time in simulation minutes (fractions are sub-minute timestamps, e.g. 800.257 is
13:20:15.4 on day 1), a priority and a unique event_id. Physical safety actions sort before ordinary ones at
the same instant. Each event is popped once; ids never repeat, so a reloaded save cannot run an
event twice.
"""
import heapq

# Lower runs first at equal time.
PRIORITY = {'protection': 0, 'topology': 1, 'restore': 2, 'equipment': 3, 'commission': 4, 'command': 5, 'economy': 6}


class EventQueue:
    def __init__(self, state=None):
        state = state or {}
        self.seq = state.get('seq', 0)
        self.heap = [tuple(item) for item in state.get('heap', [])]
        heapq.heapify(self.heap)

    def push(self, time, kind, group='equipment', **data):
        self.seq += 1
        event = dict(event_id=f'{kind}-{self.seq}', kind=kind, time=float(time), **data)
        heapq.heappush(self.heap, (float(time), PRIORITY[group], self.seq, event))
        return event

    def next_time(self):
        return self.heap[0][0] if self.heap else float('inf')

    def pop_before(self, limit):
        """Pop the earliest event strictly before `limit`, or None."""
        if self.heap and self.heap[0][0] < limit:
            return heapq.heappop(self.heap)[3]
        return None

    def cancel(self, predicate):
        """Remove queued events matching predicate(event); returns how many."""
        keep = [item for item in self.heap if not predicate(item[3])]
        removed = len(self.heap)-len(keep)
        if removed:
            self.heap = keep
            heapq.heapify(self.heap)
        return removed

    def pending(self, predicate=lambda e: True):
        return [item[3] for item in sorted(self.heap) if predicate(item[3])]

    def state(self):
        return dict(seq=self.seq, heap=[list(item) for item in sorted(self.heap)])
