"""Reviewed public race dates. No network requests or athlete data at parse time.

Update dates through review from the linked organizers, never by guessing annual
recurrence. This is a bounded seed catalog, not a complete or live race directory.
"""

import re

PA = "https://calendar.google.com/calendar/ical/uh2llv64k5hd7l4ob3gvk8qvgc%40group.calendar.google.com/public/basic.ics"
# Alternate sponsor/name aliases checked against the PA road Grand Prix listing:
# https://www.pausatf.org/data/2026/RRPurse2026.html
PA_XC = "https://calendar.google.com/calendar/ical/evdqr1mptaue1qqvr4k3o7kjl0%40group.calendar.google.com/public/basic.ics"
PA_MUT = "https://calendar.google.com/calendar/ical/2h7bl94kkf2u8nd4td6v8v3dnk%40group.calendar.google.com/public/basic.ics"
MAJORS = "https://www.baa.org/wp-content/uploads/2026/04/April14-BM26-Media-Guide-Pages_UPDATE-ForOnlineL.pdf"
CIM = "https://runcim.org/"
BIG_SUR = "https://www.bigsurmarathon.org/future-events/"
GRANDMAS = "https://grandmasmarathon.com/"
GRANDMAS_2026 = "https://grandmasmarathon.com/wp-content/uploads/2025/08/2026-Charity-Partners-Program-Overview.pdf"
VERIFIED_ON = "2026-10-29"

# (local race date, exact title aliases, primary reference)
RACES = (
    ("2026-03-07", ("NorCal John Frank Memorial 10-Mile", "NorCal 10 Mile"), PA),
    ("2026-03-22", ("Oakland Half Marathon",), PA),
    ("2026-04-12", ("Sactown Mile", "Sactown One-Mile"), PA),
    (
        "2026-04-19",
        ("Stow Lake Stampede 5K", "Jambar Impala Stampede 5k", "Impala Stampede 5k"),
        PA,
    ),
    ("2026-05-03", ("The Mile of Truth", "Devil Mountain Mile of Truth", "Mile of Truth"), PA),
    ("2026-05-25", ("Tamalpa Marin Memorial 5-Mile",), PA),
    ("2026-04-04", ("Bartley Bunny Run 5K",), PA),
    ("2026-04-26", ("Alameda Hosptial Foundation 10K", "Alameda Hospital Foundation 10K"), PA),
    ("2026-05-31", ("San Jose Half Marathon",), PA),
    ("2026-07-04", ("Heron 5K", "Blue Heron 5k"), PA),
    ("2026-08-08", ("Cooper Teare Classic Alameda 8K", "Cooper Teare Classic 8K"), PA),
    ("2026-09-27", ("Urban Cow Half Marathon", "Urban Cow"), PA),
    ("2026-11-01", ("Clarksburg Country Run Half Marathon", "Clarksburg Half Marathon"), PA),
    ("2026-12-06", ("California International Marathon", "CIM"), CIM),
    ("2026-12-20", ("Christmas Relays",), PA),
    ("2026-03-01", ("Tokyo Marathon", "Tokyo"), MAJORS),
    ("2026-04-20", ("Boston Marathon", "Boston"), MAJORS),
    ("2026-04-26", ("London Marathon", "TCS London Marathon", "London"), MAJORS),
    ("2026-08-30", ("Sydney Marathon", "TCS Sydney Marathon", "Sydney"), MAJORS),
    ("2026-09-27", ("Berlin Marathon", "BMW Berlin Marathon", "Berlin"), MAJORS),
    ("2026-10-11", ("Chicago Marathon", "Bank of America Chicago Marathon", "Chicago"), MAJORS),
    (
        "2026-11-01",
        ("New York City Marathon", "TCS New York City Marathon", "NYC", "NYC Marathon"),
        MAJORS,
    ),
    (
        "2026-04-26",
        ("Big Sur International Marathon", "Big Sur Marathon", "Big Sur"),
        "https://www.bigsurmarathon.org/wp-content/uploads/2026/02/2026-BSM-Mailer-Web.pdf",
    ),
    ("2027-04-25", ("Big Sur International Marathon", "Big Sur Marathon", "Big Sur"), BIG_SUR),
    ("2028-04-30", ("Big Sur International Marathon", "Big Sur Marathon", "Big Sur"), BIG_SUR),
    ("2029-04-29", ("Big Sur International Marathon", "Big Sur Marathon", "Big Sur"), BIG_SUR),
    ("2030-04-28", ("Big Sur International Marathon", "Big Sur Marathon", "Big Sur"), BIG_SUR),
    ("2026-06-20", ("Grandma's Marathon", "Grandma's", "Grandmas"), GRANDMAS_2026),
    ("2027-06-19", ("Grandma's Marathon", "Grandma's", "Grandmas"), GRANDMAS),
    ("2026-01-10", ("No Hands Trail Half Marathon",), PA_MUT),
    ("2026-01-31", ("Jed Smith 50K",), PA_MUT),
    ("2026-03-14", ("Marin Ultra Challenge 50-Mile",), PA_MUT),
    ("2026-03-21", ("Rattlesnake Dick 25K",), PA_MUT),
    ("2026-04-04", ("Diablo Trail Half Marathon",), PA_MUT),
    ("2026-04-18", ("Horseshoe Lake 30K",), PA_MUT),
    ("2026-05-09", ("Quicksilver 100K",), PA_MUT),
    ("2026-05-16", ("Silver State 50K",), PA_MUT),
    ("2026-06-13", ("San Francisco Half Day 12-Hour",), PA_MUT),
    ("2026-08-02", ("Skyline 50K",), PA_MUT),
    (
        "2026-08-15",
        ("Tamalpa Headlands 50K (USATF National Champs)", "Tamalpa Headlands 50K"),
        PA_MUT,
    ),
    ("2026-08-23", ("25th Annual SCTC XC Challenge", "SCTC XC Challenge"), PA_XC),
    ("2026-08-30", ("33rd Annual Phil Widener Empire Open", "Phil Widener Empire Open"), PA_XC),
    ("2026-09-12", ("Stevens Crk. Striders Reservoir Trail Half Marathon",), PA_MUT),
    ("2026-09-13", ("40th Annual GGP Open", "GGP Open"), PA_XC),
    ("2026-09-19", ("15th Annual Rebels XC Challenge", "Rebels XC Challenge"), PA_XC),
    ("2026-09-26", ("Dick Collins Firetrails 50-Mile",), PA_MUT),
    ("2026-10-03", ("21st Annual Garin Park XC Challenge", "Garin Park XC Challenge"), PA_XC),
    ("2026-10-03", ("Star City San Bruno Mtn. Trail Half Marathon",), PA_MUT),
    ("2026-10-10", ("Ruth Anderson Memorial Run 50K & 50 Mile",), PA_MUT),
    (
        "2026-10-11",
        ("30th Annual John Lawson Tamalpa Challenge", "John Lawson Tamalpa Challenge"),
        PA_XC,
    ),
    ("2026-10-17", ("17th Annual Willow Hills XC Open", "Willow Hills XC Open"), PA_XC),
    ("2026-10-24", ("28th Annual Matt Yeo Aggies XC Open", "Matt Yeo Aggies XC Open"), PA_XC),
    ("2026-11-15", ("40th Annual PA XC Championships", "PA XC Championships"), PA_XC),
)


def normalized_name(value):
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def race_date_matches(title, day):
    """True/False for a known exact alias; None when the name is not cataloged."""
    name = normalized_name(title)
    dates = {
        date
        for date, aliases, _ in RACES
        if any(normalized_name(alias) == name for alias in aliases)
    }
    return day in dates if dates else None
