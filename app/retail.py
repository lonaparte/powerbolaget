"""Retail offers and signed contracts, prices in SEK/kWh, simulation time in minutes.

Policy edits affect offers only. Signed fees, markup, index and expiry are immutable.
Renewals compare expected cost plus a small risk premium without future information.
"""
from .calendar import DAY
from .params import NETWORK_FEE, RETAIL_MARGIN, INDUSTRY_CONTRACT_DISCOUNT, WAGE


def default_policy():
    return {cls: dict(network_fee=fee, fixed_markup=(-.62*INDUSTRY_CONTRACT_DISCOUNT if cls == 'industry' else .09),
                     floating_markup=RETAIL_MARGIN, fixed_days=365, floating_days=30,
                     floating_index='spot' if cls == 'industry' else 'monthly')
            for cls, fee in NETWORK_FEE.items()}


def category(f):
    return 'industry' if f['kind'] in ('cement', 'quarry', 'dairy', 'feedmill', 'slaughter', 'brewery') else 'business'


def offer(world, cls, mode, now):
    p = world.retail_policy[cls]
    return dict(category=cls, mode=mode, signed=now, expires=now+p[mode+'_days']*DAY,
                network_fee=p['network_fee'], markup=p[mode+'_markup'], index=p['floating_index'],
                fixed_energy=max(0., world.price_avg+p['fixed_markup']), policy_version=world.retail_version)


def contract(world, owner, cls, now):
    c = world.contracts.get(owner)
    if c is None or now >= c['expires']:
        fixed, floating = offer(world, cls, 'fixed', now), offer(world, cls, 'floating', now)
        # Firms/households choose using known mean price, plus aversion to spot-price uncertainty.
        risk = .04 if cls == 'industry' else .02
        mode = 'fixed' if fixed['fixed_energy'] <= world.price_avg+floating['markup']+risk else 'floating'
        if c is None:  # opening contracts retain the established baseline terms
            mode = 'fixed' if cls == 'industry' else 'floating'
        c = fixed if mode == 'fixed' else floating
        world.contracts[owner] = c
    return c


def price(world, cls, now, owner=None):
    c = contract(world, owner, cls, now) if owner else offer(world, cls, 'floating', now)
    if c['mode'] == 'fixed':
        return c['fixed_energy']+c['network_fee']
    index = world.energy_price(now) if c['index'] == 'spot' else world.price_avg
    return max(0., index+c['markup'])+c['network_fee']


def expected_price(world, cls, now, owner):
    c = contract(world, owner, cls, now)
    return ((c['fixed_energy'] if c['mode'] == 'fixed' else max(0., world.price_avg+c['markup']))
            +c['network_fee'])


def change_policy(world, cls, changes):
    if cls not in world.retail_policy:
        raise ValueError('Unknown retail customer group.')
    allowed = set(default_policy()[cls])
    if set(changes)-allowed:
        raise ValueError('Unknown retail policy field.')
    candidate = dict(world.retail_policy[cls], **changes)
    for key in ('network_fee', 'fixed_markup', 'floating_markup'):
        if not -.5 <= candidate[key] <= 5 or (key == 'network_fee' and candidate[key] < 0):
            raise ValueError('Retail prices must be within the published policy range.')
    for key in ('fixed_days', 'floating_days'):
        if not 1 <= candidate[key] <= 1095:
            raise ValueError('Contract duration must be 1–1095 days.')
    if candidate['floating_index'] not in ('spot', 'monthly'):
        raise ValueError('Price index must be spot or monthly.')
    world.retail_policy[cls] = candidate
    world.retail_version += 1


def close_month(world):
    """Last complete calendar month's observed average; no exponentially lagged approximation."""
    if world.price_observations['hours']:
        world.price_avg = world.price_observations['sum']/world.price_observations['hours']
    world.price_observations = dict(sum=0., hours=0)
