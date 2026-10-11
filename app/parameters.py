"""Reference data and explicit design assumptions. See docs/MODEL.md."""
VERSION = '0.0.1'
DT_H = .25
TURBINE = dict(rated_mw=5., rotor_m=126., hub_m=90., cut_in=3., rated_speed=11.4,
               cut_out=25., restart_speed=20., restart_steps=2, rho_ref=1.225)
DISTRICTS = [
    dict(id='harbor', name='Harbor & cold chain', peak_mw=3.2, pf=.94, critical=.55, km=3.4, amps=260),
    dict(id='center', name='Waterfront center', peak_mw=3.5, pf=.96, critical=.3, km=2.2, amps=300),
    dict(id='homes', name='Bay residences', peak_mw=4.2, pf=.97, critical=.2, km=4.1, amps=320),
    dict(id='water', name='Water & hospital', peak_mw=1.8, pf=.95, critical=.85, km=1.8, amps=160),
]
PROJECTS = [
    dict(id='wind_phase2', name='Wind phase 2 · +20 MW', cost=140_000_000, days=180,
         description='Add four 5 MW turbines and unit transformers. Total capacity: 40 MW. No generation before commissioning.'),
    dict(id='battery_phase2', name='Storage expansion · +6 MW / 24 MWh', cost=32_000_000, days=90,
         description='Double PCS and battery capacity to 12 MW / 48 MWh. Initial charge is purchased and metered.'),
    dict(id='collector_upgrade', name='Upgrade both collectors', cost=16_000_000, days=120,
         description='Upgrade both main collectors from 300 A to 500 A to reduce thermal constraints.'),
]
WEATHER = {'normal':'Baltic coastal city climate', 'calm':'Low-wind test', 'storm':'Storm test', 'variable':'Gust test'}
INITIAL_TURBINES = {0, 1, 4, 5}
TURBINES = [dict(id=f'WT{i+1:02}', string='a' if i<4 else 'b',
                 x_m=(i%4)*882., y_m=(i//4)*630.) for i in range(8)]
LIMITATIONS = [
    '15-minute quasi-static power flow; faults and protection are separate event calculations, not EMT or stability studies.',
    'The 5 MW reference points come from NREL. Curve interpolation, weather synthesis, wake coefficients and site parameters are reviewable assumptions.',
    'No measured wind series or vendor controllers are connected. Grid-code compliance and engineering relay settings are not certified.',
    'Grid-connected operation with anti-islanding trips. Grid-following storage cannot black-start.',
]
