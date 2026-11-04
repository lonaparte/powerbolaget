"""Game assumptions in one place. Every number here is a reviewable assumption (provenance
'assumption'), chosen for plausible orders of magnitude, not a measurement of Gotland or any firm."""

POP_CAP = 10_000                 # hard limit on POP objects, residents and visitors together (spec 0.1.6)
HOUSEHOLD_SIZE = 2.1
SECTORS = ('industry', 'agriculture', 'hospitality', 'services', 'public', 'construction')
WAGE = dict(industry=245., agriculture=175., hospitality=165., services=200., public=210., construction=230.)  # SEK/h
SHIFT_HOURS = 8.0
INCOME_TAX = .32
PENSION_DAY = 460.               # SEK per retiree and day
CHILD_DAY = 45.                  # SEK per child and day, from the region
FAMILY_SUPPORT_DAY = 110.        # SEK per child and day, paid by working adults of the same zone
UNEMPLOYMENT_DAY = 360.          # SEK per unemployed person and day
HOUSING_DAY = 170.               # SEK per adult and day: rent and mortgages
HOUSING_LOCAL_SHARE = .35        # of housing costs spent on local maintenance and renovation (construction)
PUBLIC_WORKS_DAY = 2.4e6         # SEK per day of public construction bought by the region
MOVING_WEALTH = 30000.           # SEK an immigrant brings
OTHER_EXTERNAL_DAY = 95.         # SEK per resident and day: cars, fuel, insurance, online purchases
SAVING_TARGET_DAYS = 90          # wealth households try to hold, in days of income

# Goods: unit, mainland reference price SEK/unit, freight SEK/unit, tradable with the mainland.
GOODS = {
    'limestone': ('t', 230., 45., True),
    'cement': ('t', 1180., 140., True),
    'grain': ('t', 2350., 220., True),
    'milk': ('t', 4900., 600., True),
    'livestock': ('t', 23000., 1500., True),
    'feed': ('t', 3300., 300., True),
    'food': ('t', 34000., 2200., True),
    'fuel': ('MWh', 260., 30., True),           # coal and petroleum coke for the kiln
    'consumer': ('basket', 1000., 0., False),   # local retail and personal services, per 1000 SEK basket
    'lodging': ('guest-night', 980., 0., False),
    'ferry': ('trip', 420., 0., False),
    'construction': ('work unit', 1000., 0., False),
}
IMPORT_SHARE = dict(consumer=.42, construction=.45)   # SEK of off-island goods bought per SEK of output

# Electricity: mainland reference price (SEK/kWh) and tariffs.
PRICE_BASE = .62
NETWORK_FEE = dict(household=.32, business=.24, industry=.09)
RETAIL_MARGIN = .06
INDUSTRY_CONTRACT_DISCOUNT = .05
EXPORT_FEE = .03                 # SEK/kWh paid on exports to the mainland

# Powerbolaget costs.
WIND_OM_SEK_MW_YEAR = 430_000
GRID_OM_SEK_KM_YEAR = 38_000
STORAGE_OM_SEK_MW_YEAR = 90_000
STARTING_CASH = 400e6

# Construction cost assumptions (MSEK).
COST = dict(collector_km=2.4, farm_substation=42., transformer_unit=31., storage_mw=4.6, storage_mwh=2.4,
            grid_forming_extra=.15)
DAYS = dict(storage=240, line_ohl=420, line_cable=330, transformer=270, farm_substation=365)
LOCAL_CONSTRUCTION_SHARE = .35

# Tourism.
VISITORS_PER_YEAR = 780_000
STAY_DAYS = 3.6
HOLIDAY_PERSONS = 2.8
TOURIST_BUDGET_DAY = 900.        # SEK per visitor and day besides lodging (meals, shops, activities)

# Demography (per year).
BIRTH_RATE = .0092
DEATH_RATE = .0108
MOVE_RATE = .055                 # share of working-age residents who consider moving each year
EMIGRATION_SHARE = .35           # of movers, how many look off-island
IMMIGRATION_PER_YEAR = 1800
