"""Whole-session timing histograms; quantile buckets have 2% relative width."""
from math import ceil,log


class Timing:
    def __init__(self):
        self.count=0;self.total=0.;self.minimum=float('inf');self.maximum=0.;self.bins={}

    def add(self,ms):
        self.count+=1;self.total+=ms;self.minimum=min(self.minimum,ms);self.maximum=max(self.maximum,ms)
        key=max(0,int(log(max(.01,ms)/.01)/log(1.02)))
        self.bins[key]=self.bins.get(key,0)+1

    def summary(self):
        def quantile(q):
            target=ceil(self.count*q);seen=0
            for key,n in sorted(self.bins.items()):
                seen+=n
                if seen>=target:return round(.01*1.02**(key+1),5)
        return dict(count=self.count,mean_ms=self.total/self.count if self.count else None,
                    min_ms=self.minimum if self.count else None,max_ms=self.maximum if self.count else None,
                    p50_ms=quantile(.5),p95_ms=quantile(.95),quantile_method='whole-session histogram; 2% bucket upper bounds')
