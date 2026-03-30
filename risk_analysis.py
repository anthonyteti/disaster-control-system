neighborhoods = [
    {"id": "Downtown",    "bounds": [[0, 3], [0, 3]], "risk_level": 0.3},
    {"id": "Suburb",      "bounds": [[3, 7], [0, 3]], "risk_level": 0.6},
    {"id": "Industrial",  "bounds": [[0, 3], [3, 7]], "risk_level": 0.9},
    {"id": "Residential", "bounds": [[3, 7], [3, 7]], "risk_level": 0.5},
]

_DEFAULT_RISK = 0.5
_GRID_SIZE    = 7

HISTORICAL_INCIDENT_DATA = {
    "Downtown":    12,
    "Suburb":      28,
    "Industrial":  55,
    "Residential": 20,
}

_HISTORICAL_MAX = max(HISTORICAL_INCIDENT_DATA.values())

_active_incidents = {nb["id"]: 0 for nb in neighborhoods}

_HISTORICAL_WEIGHT = 0.3
_DYNAMIC_WEIGHT    = 0.25
_DYNAMIC_CAP       = 0.4


def _build_lookup_table():
    table = {}
    for nb in neighborhoods:
        (x1, x2), (y1, y2) = nb["bounds"]
        for x in range(x1, x2):
            for y in range(y1, y2):
                table[(x, y)] = nb["id"]
    return table

_CELL_TO_NEIGHBORHOOD = _build_lookup_table()


def _get_neighborhood_id(location):
    return _CELL_TO_NEIGHBORHOOD.get((location[0], location[1]))


def register_active_incident(location):
    nb_id = _get_neighborhood_id(location)
    if nb_id and nb_id in _active_incidents:
        _active_incidents[nb_id] += 1


def resolve_active_incident(location):
    nb_id = _get_neighborhood_id(location)
    if nb_id and nb_id in _active_incidents:
        _active_incidents[nb_id] = max(0, _active_incidents[nb_id] - 1)


def get_neighborhood_risk(location):
    nb_id = _get_neighborhood_id(location)

    if nb_id is None:
        return _DEFAULT_RISK

    nb = next(n for n in neighborhoods if n["id"] == nb_id)
    base_risk = nb["risk_level"]

    historical_count = HISTORICAL_INCIDENT_DATA.get(nb_id, 0)
    historical_boost = _HISTORICAL_WEIGHT * (historical_count / _HISTORICAL_MAX)

    active_count = _active_incidents.get(nb_id, 0)
    dynamic_boost = min(_DYNAMIC_CAP, active_count * _DYNAMIC_WEIGHT)

    effective_risk = round(min(1.0, base_risk + historical_boost + dynamic_boost), 2)
    return effective_risk


def get_incident_risk(location, severity):
    severity = max(1, min(severity, 5))
    base_risk = get_neighborhood_risk(location)
    severity_factor = severity / 5.0
    return round(min(1.0, base_risk * severity_factor), 2)


def get_risk_heatmap():
    heatmap = []
    for x in range(_GRID_SIZE):
        for y in range(_GRID_SIZE):
            nb_id = _get_neighborhood_id([x, y])
            risk  = get_neighborhood_risk([x, y])
            heatmap.append({
                "x":            x,
                "y":            y,
                "neighborhood": nb_id if nb_id else "Unknown",
                "risk":         risk,
            })
    return heatmap


def get_neighborhood_summary():
    summary = []
    for nb in neighborhoods:
        nb_id     = nb["id"]
        (x1, x2), (y1, y2) = nb["bounds"]
        sample_loc = [x1, y1]
        summary.append({
            "neighborhood":      nb_id,
            "base_risk":         nb["risk_level"],
            "historical_incidents": HISTORICAL_INCIDENT_DATA.get(nb_id, 0),
            "active_incidents":  _active_incidents.get(nb_id, 0),
            "effective_risk":    get_neighborhood_risk(sample_loc),
        })
    return summary


def get_relocation_suggestions(units):
    suggestions = []

    for nb in neighborhoods:
        nb_id = nb["id"]
        (x1, x2), (y1, y2) = nb["bounds"]

        center = [(x1 + x2) // 2, (y1 + y2) // 2]
        effective_risk = get_neighborhood_risk(center)

        if effective_risk <= 0.7:
            continue

        def in_or_near_zone(unit_loc):
            return x1 <= unit_loc[0] < x2 and y1 <= unit_loc[1] < y2

        zone_covered = any(
            in_or_near_zone(u["location"])
            for u in units
            if u["status"] == "available"
        )
        if zone_covered:
            continue

        available = [u for u in units if u["status"] == "available"]
        if not available:
            continue

        best = min(available, key=lambda u: (
            abs(u["location"][0] - center[0]) + abs(u["location"][1] - center[1])
        ))

        suggestions.append({
            "unit_id":           best["unit_id"],
            "unit_type":         best["unit_type"],
            "current_location":  best["location"],
            "suggested_location": center,
            "neighborhood":      nb_id,
            "effective_risk":    effective_risk,
            "reason":            f"{nb_id} risk={effective_risk} > 0.7, no unit on site",
        })

    return suggestions
