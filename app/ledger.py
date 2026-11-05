"""Double-entry money ledger in SEK.

Every payment moves money from one account to another, so the sum over all accounts never changes.
Starting balances come from the 'genesis' account; 'external' is the mainland economy (imports,
exports, tourists' home income, state grants) and 'financing' records injections that keep
Powerbolaget solvent under the free-investment rule.
"""
from collections import defaultdict, deque


class Ledger:
    def __init__(self, state=None):
        state = state or {}
        self.accounts = defaultdict(float, state.get('accounts', {}))
        self.quantities=defaultdict(float,state.get('quantities',{}))
        self.totals = defaultdict(float, state.get('totals', {}))     # cumulative SEK by category
        self.today = defaultdict(float, state.get('today', {}))       # current day, by category
        self.journal = deque(state.get('journal', []), maxlen=300)    # latest entries, for inspection

    def endow(self, account, amount):
        self.transfer('genesis', account, amount, 'opening balance')

    def transfer(self, payer, payee, amount, category, t=None, good=None, qty=None):
        if good and qty and qty>0:
            if category.startswith('import:') and payer.startswith('firm:'):
                self.quantities[good]+=qty
            elif category.startswith('export:') or category=='liquidation inventory':
                self.quantities[good]-=qty
            elif category.startswith('goods:') and not payer.startswith('firm:'):
                self.quantities[good]-=qty
        if amount == 0:
            return
        if amount < 0:
            payer, payee, amount = payee, payer, -amount
        self.accounts[payer] -= amount
        self.accounts[payee] += amount
        self.totals[category] += amount
        self.today[category] += amount
        if t is not None and amount >= 1000:
            self.journal.append([round(t, 3), payer, payee, round(amount, 2), category, good, qty])

    def balance(self, account):
        return self.accounts.get(account, 0.0)

    def close_day(self):
        day, self.today = dict(self.today), defaultdict(float)
        return day

    def state(self):
        return dict(accounts=dict(self.accounts), totals=dict(self.totals), today=dict(self.today), journal=list(self.journal),quantities=dict(self.quantities))
