"""Parse the subset of OSM `opening_hours` syntax present in our dataset into
the app's {day: [[open, close], ...]} shape.

Supported: "24/7", day ranges/lists (Mo-Fr, Mo,Fr-Su), multiple semicolon-
separated rules, "off" rules, bare time ranges applying to all days, the
"PH" public-holiday token (ignored), and "sunset"/"sunrise" (approximated,
since the app has no solar calculator). Anything unrecognised raises, so an
unparsed tag fails loudly instead of silently producing wrong hours.
"""

import re

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
OSM_DAY = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}

# The app has no solar model; approximate Florida's mean civil twilight.
SOLAR = {"sunset": "19:30", "sunrise": "06:45", "dusk": "19:45", "dawn": "06:30"}


def expand_days(spec):
    """'Mo-Fr' | 'Mo,Fr-Su' | 'Mo' -> set of weekday indices."""
    out = set()
    for part in spec.split(","):
        part = part.strip().lower()
        if not part or part == "ph":       # public holidays: not modelled
            continue
        if "-" in part:
            a, b = (p.strip() for p in part.split("-", 1))
            if a not in OSM_DAY or b not in OSM_DAY:
                raise ValueError(f"bad day range {part!r}")
            i, j = OSM_DAY[a], OSM_DAY[b]
            out |= {d % 7 for d in range(i, (j if j >= i else j + 7) + 1)}
        else:
            if part not in OSM_DAY:
                raise ValueError(f"bad day {part!r}")
            out.add(OSM_DAY[part])
    return out


def norm_time(t):
    t = t.strip().lower()
    if t in SOLAR:
        return SOLAR[t]
    if not re.fullmatch(r"\d{1,2}:\d{2}", t):
        raise ValueError(f"bad time {t!r}")
    h, m = t.split(":")
    return f"{int(h):02d}:{m}"


def parse(tag):
    """OSM opening_hours string -> {day: [[open, close]] or None}."""
    tag = tag.strip()
    if tag in ("24/7", "Mo-Su 00:00-24:00"):
        return {d: [["00:00", "24:00"]] for d in DAYS}

    # A comma separates time spans ("Mo 09:00-12:00,13:00-17:00") but also
    # whole rules ("Su 10:00-22:00, Mo-Sa 11:30-22:00"). Only the latter has a
    # digit before the comma and a day after it; rewrite those to ';' so day
    # lists like "Mo,Fr-Su" are left alone.
    tag = re.sub(r"(?<=\d)\s*,\s*(?=(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)\b)", "; ", tag)

    result = {d: None for d in DAYS}
    for rule in (r.strip() for r in tag.split(";")):
        if not rule:
            continue

        # Split on where the time part starts, so a multi-token day spec like
        # "Mo-Su, PH" stays intact. A rule with no day spec applies to all days.
        m = re.match(
            r"^(.*?)\s*((?:\d{1,2}:\d{2}|sunrise|sunset|dawn|dusk|off).*)$",
            rule, re.IGNORECASE)
        if not m:
            raise ValueError(f"unparsed rule {rule!r} in {tag!r}")
        day_spec, rest = m.group(1).strip(), m.group(2).strip()
        days = expand_days(day_spec) if day_spec else expand_days("Mo-Su")
        if not days:                      # e.g. a "PH"-only rule
            continue

        if rest.lower() == "off":
            for d in days:
                result[DAYS[d]] = None
            continue

        ranges = []
        for span in rest.split(","):
            span = span.strip()
            if not span or span.lower() == "off":
                continue
            mm = re.match(r"^([\w:]+)\s*-\s*([\w:]+)$", span)
            if not mm:
                raise ValueError(f"unparsed span {span!r} in {tag!r}")
            ranges.append([norm_time(mm.group(1)), norm_time(mm.group(2))])

        if not ranges:
            continue
        for d in days:
            result[DAYS[d]] = [list(r) for r in ranges]

    if all(v is None for v in result.values()):
        raise ValueError(f"tag produced no open hours: {tag!r}")
    return result


if __name__ == "__main__":
    tests = [
        "24/7",
        "Sa-Su 00:00-16:00",
        "Tu-Su 11:00-19:00",
        "Mo-Th 08:00-24:00; Su 09:00-24:00",
        "Mo,Fr-Su 11:00-18:00; Tu-We off",
        "Mo-Su, PH 08:00-sunset",
        "Mo-Fr 07:00-13:00; Sa-Su 08:00-13:00",
        "Su 10:00-22:00, Mo-Sa 11:30-22:00",
        "10:00-17:00",
    ]
    for t in tests:
        print(f"{t:38} -> {parse(t)}")
