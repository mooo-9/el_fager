"""
Unit conversion for El Fager.

Convert between temperature, weight, distance, volume, speed, area, data size, time, pressure.
Pure Python — no external dependencies.
"""

_CONVERSIONS = {
    # Length — base: meter
    "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
    "inch": 0.0254, "in": 0.0254, "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "yd": 0.9144, "yard": 0.9144, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "nm": 1852.0, "nautical mile": 1852.0,

    # Weight/Mass — base: kilogram
    "mg": 0.000001, "g": 0.001, "kg": 1.0, "tonne": 1000.0, "t": 1000.0,
    "oz": 0.028349523, "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237,
    "stone": 6.35029, "ton": 907.185, "short ton": 907.185,

    # Volume — base: liter
    "ml": 0.001, "cl": 0.01, "dl": 0.1, "l": 1.0, "liter": 1.0, "litre": 1.0,
    "m3": 1000.0, "gallon": 3.78541, "gal": 3.78541, "quart": 0.946353,
    "pint": 0.473176, "cup": 0.236588, "fl oz": 0.029574, "tbsp": 0.014787, "tsp": 0.004929,

    # Speed — base: m/s
    "m/s": 1.0, "km/h": 0.27778, "kph": 0.27778, "mph": 0.44704,
    "knot": 0.514444, "ft/s": 0.3048,

    # Area — base: m2
    "mm2": 0.000001, "cm2": 0.0001, "m2": 1.0, "km2": 1000000.0,
    "in2": 0.00064516, "ft2": 0.092903, "yd2": 0.836127,
    "acre": 4046.86, "hectare": 10000.0, "ha": 10000.0, "mi2": 2589988.0,

    # Data — base: byte
    "bit": 0.125, "byte": 1.0,
    "kb": 1000.0, "mb": 1000000.0, "gb": 1e9, "tb": 1e12, "pb": 1e15,
    "kib": 1024.0, "mib": 1048576.0, "gib": 1073741824.0, "tib": 1099511627776.0,

    # Time — base: second
    "ms": 0.001, "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0,
    "min": 60.0, "minute": 60.0, "minutes": 60.0,
    "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "day": 86400.0, "days": 86400.0,
    "week": 604800.0, "weeks": 604800.0,
    "month": 2592000.0, "year": 31536000.0,

    # Pressure — base: Pascal
    "pa": 1.0, "kpa": 1000.0, "mpa": 1000000.0,
    "bar": 100000.0, "psi": 6894.76, "atm": 101325.0, "mmhg": 133.322, "torr": 133.322,
}

_TEMP_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin"}

_CATEGORIES = {
    "length":   {"mm", "cm", "m", "km", "inch", "in", "ft", "foot", "feet", "yd", "yard", "mi", "mile", "miles", "nm", "nautical mile"},
    "weight":   {"mg", "g", "kg", "tonne", "t", "oz", "lb", "lbs", "pound", "stone", "ton", "short ton"},
    "volume":   {"ml", "cl", "dl", "l", "liter", "litre", "m3", "gallon", "gal", "quart", "pint", "cup", "fl oz", "tbsp", "tsp"},
    "speed":    {"m/s", "km/h", "kph", "mph", "knot", "ft/s"},
    "area":     {"mm2", "cm2", "m2", "km2", "in2", "ft2", "yd2", "acre", "hectare", "ha", "mi2"},
    "data":     {"bit", "byte", "kb", "mb", "gb", "tb", "pb", "kib", "mib", "gib", "tib"},
    "time":     {"ms", "s", "sec", "second", "seconds", "min", "minute", "minutes", "hr", "hour", "hours", "day", "days", "week", "weeks", "month", "year"},
    "pressure": {"pa", "kpa", "mpa", "bar", "psi", "atm", "mmhg", "torr"},
}


def _to_celsius(value: float, unit: str) -> float:
    u = unit.lower()
    if u in ("c", "celsius"):
        return value
    elif u in ("f", "fahrenheit"):
        return (value - 32) * 5 / 9
    elif u in ("k", "kelvin"):
        return value - 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


def _from_celsius(value: float, unit: str) -> float:
    u = unit.lower()
    if u in ("c", "celsius"):
        return value
    elif u in ("f", "fahrenheit"):
        return value * 9 / 5 + 32
    elif u in ("k", "kelvin"):
        return value + 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """Convert value from one unit to another across any supported category."""
    try:
        fu = from_unit.lower().strip()
        tu = to_unit.lower().strip()

        if fu in _TEMP_UNITS or tu in _TEMP_UNITS:
            celsius = _to_celsius(value, fu)
            result = _from_celsius(celsius, tu)
            return f"{value} {from_unit} = {result:.4g} {to_unit}"

        if fu not in _CONVERSIONS:
            return f"[convert_units: unknown unit '{from_unit}'. Call list_unit_categories to see supported units.]"
        if tu not in _CONVERSIONS:
            return f"[convert_units: unknown unit '{to_unit}'. Call list_unit_categories to see supported units.]"

        from_cat = next((cat for cat, units in _CATEGORIES.items() if fu in units), None)
        to_cat = next((cat for cat, units in _CATEGORIES.items() if tu in units), None)
        if from_cat and to_cat and from_cat != to_cat:
            return f"[convert_units: cannot convert {from_unit} ({from_cat}) to {to_unit} ({to_cat}) — different unit categories]"

        base_value = value * _CONVERSIONS[fu]
        result = base_value / _CONVERSIONS[tu]
        return f"{value} {from_unit} = {result:.6g} {to_unit}"
    except Exception as e:
        return f"[convert_units failed: {e}]"


def list_unit_categories() -> str:
    """List all supported unit categories and units."""
    return (
        "Supported unit categories:\n\n"
        "Temperature:  C/celsius, F/fahrenheit, K/kelvin\n"
        "Length:       mm, cm, m, km, in/inch, ft/foot, yd/yard, mi/mile, nm (nautical)\n"
        "Weight:       mg, g, kg, tonne, oz, lb/lbs, stone, ton\n"
        "Volume:       ml, cl, l/liter, m3, gallon/gal, quart, pint, cup, fl oz, tbsp, tsp\n"
        "Speed:        m/s, km/h/kph, mph, knot, ft/s\n"
        "Area:         mm2, cm2, m2, km2, in2, ft2, yd2, acre, hectare/ha, mi2\n"
        "Data:         bit, byte, kb, mb, gb, tb, pb, kib, mib, gib, tib\n"
        "Time:         ms, s/sec, min, hr/hour, day, week, month, year\n"
        "Pressure:     pa, kpa, mpa, bar, psi, atm, mmhg/torr\n\n"
        "Usage: convert_units(value=100, from_unit='km', to_unit='miles')"
    )
