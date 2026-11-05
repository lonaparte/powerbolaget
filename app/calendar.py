"""Fantasy Era calendar (幻想纪元).

Simulation minute 0 is year 1, 1 January, 00:00, a Monday. Years have 365 days with the usual month
lengths and no leap days. Clock time is fixed local time without daylight saving, so no hour is
repeated or skipped.
"""
ERA = 'Fantasy Era'
ERA_SHORT = 'FE'
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
HOUR = 60
DAY = 1440
YEAR_DAYS = 365
YEAR = DAY*YEAR_DAYS
_MONTH_START = [sum(DAYS_IN_MONTH[:m]) for m in range(12)]
# Public holidays shift activity like a Sunday (day of year, 0-based).
HOLIDAYS = {0: 'New Year', 170: 'Midsummer Eve', 171: 'Midsummer Day', 357: 'Christmas Eve', 358: 'Christmas Day',
            359: 'Boxing Day', 364: "New Year's Eve"}


def parts(minute):
    """Calendar fields of a simulation minute (an int or float; fractions are ignored)."""
    minute = int(minute)
    day_index, clock = divmod(minute, DAY)
    year, doy = divmod(day_index, YEAR_DAYS)
    month = max(m for m in range(12) if _MONTH_START[m] <= doy)
    return dict(year=year+1, month=month+1, day=doy-_MONTH_START[month]+1, hour=clock//60, minute=clock % 60,
                weekday=day_index % 7, doy=doy, day_index=day_index)


def is_rest_day(minute):
    p = parts(minute)
    return p['weekday'] >= 5 or p['doy'] in HOLIDAYS


def month_index(minute):
    """Months elapsed since the start of the era."""
    p = parts(minute)
    return (p['year']-1)*12+p['month']-1


def label(minute, seconds=False):
    """'FE 1 · 01 Jan · 00:00', for display."""
    p = parts(minute)
    clock = f"{p['hour']:02d}:{p['minute']:02d}"
    if seconds:
        clock += f':{(minute*60) % 60:04.1f}'
    return f"{ERA_SHORT} {p['year']} · {p['day']:02d} {MONTHS[p['month']-1]} · {clock}"


def stamp(minute):
    """Sortable timestamp for messages and logs: 'FE0001-01-01T00:00:00'."""
    p = parts(minute)
    second = (minute*60) % 60
    return f"FE{p['year']:04d}-{p['month']:02d}-{p['day']:02d}T{p['hour']:02d}:{p['minute']:02d}:{second:06.3f}"
