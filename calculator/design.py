"""Diseño discreto de P05: identidades económicas, escalas y vecinos."""

from decimal import Decimal as D
from itertools import product


LENGTHS = (1, 2, 3, 5, 7)
SCALES = {
    "broad": {"P-SMA": ((150, None), (200, None), (250, None)),
              "MOM": ((189, None), (252, None), (315, None)),
              "MR-Z": tuple(product((15, 20, 25), (D("1.5"), D("2"), D("2.5"))))},
    "local": {"P-SMA": ((190, None), (200, None), (210, None)),
              "MOM": ((239, None), (252, None), (265, None)),
              "MR-Z": tuple(product((19, 20, 21), (D("1.9"), D("2"), D("2.1"))))},
}
CENTERS = {"P-SMA": 200, "MOM": 252, "MR-Z": 20}


def number(value):
    return format(D(value).normalize(), "f")


def config_key(family, sessions, threshold):
    prefix = {"P-SMA": "sma", "MOM": "mom", "MR-Z": "mrz"}[family]
    return prefix + str(sessions) + ("-" + number(threshold).replace(".", "p") if threshold is not None else "")


def configurations(instrument="SPY"):
    found = {}
    for scale in SCALES.values():
        for family, values in scale.items():
            for sessions, threshold in values:
                key = config_key(family, sessions, threshold)
                found[key] = {"config_key": key, "configuration_id": f"{instrument}-{family}-{sessions}" + ("-" + number(threshold) if threshold is not None else ""),
                              "instrument_id": instrument, "family": family, "sessions": sessions,
                              "entry_threshold": threshold, "label": f"{family}({sessions}" + ("; " + number(threshold) if threshold is not None else "") + ")"}
    return list(found.values())


CONFIGURATIONS = configurations()
RULES = {c["config_key"]: (c["family"], c["sessions"], c["entry_threshold"]) for c in CONFIGURATIONS}


def memberships():
    return [{"config_key": config_key(family, sessions, threshold), "scale": scale}
            for scale, families in SCALES.items() for family, values in families.items() for sessions, threshold in values]


def neighbors():
    result = []
    for scale, families in SCALES.items():
        for family, values in families.items():
            for parameter, position in (("sessions", 0), ("entry_threshold", 1)):
                if position == 1 and family != "MR-Z":
                    continue
                groups = {}
                for pair in values:
                    groups.setdefault(pair[1 - position], []).append(pair)
                for group in groups.values():
                    ordered = sorted(group, key=lambda pair: pair[position])
                    for left, right in zip(ordered, ordered[1:]):
                        center = D(CENTERS[family] if position == 0 else 2)
                        a, b = D(left[position]), D(right[position])
                        result.append({"scale": scale, "family": family, "parameter": parameter,
                                       "left_config": config_key(family, *left), "right_config": config_key(family, *right),
                                       "left_parameter": a, "right_parameter": b, "absolute_step": b - a,
                                       "relative_step": (b - a) / center,
                                       "left_distance_from_center": (a - center) / center,
                                       "right_distance_from_center": (b - center) / center})
    return result
