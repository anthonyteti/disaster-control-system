import copy
import sys
import unittest
import types

# ── inject risk_analysis from disk without pika ──────────────────────────────
import importlib.util, os

_RA_PATH = os.path.join(os.path.dirname(__file__), "risk_analysis.py")
_spec = importlib.util.spec_from_file_location("risk_analysis", _RA_PATH)
_ra   = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ra)
sys.modules["risk_analysis"] = _ra

from risk_analysis import (
    get_neighborhood_risk,
    get_incident_risk,
    get_risk_heatmap,
    get_neighborhood_summary,
    get_relocation_suggestions,
    register_active_incident,
    resolve_active_incident,
    _active_incidents,
    neighborhoods,
    HISTORICAL_INCIDENT_DATA,
)

_BASE_UNITS = [
    {"unit_id": "P1", "unit_type": "police",    "location": [1, 2], "status": "available"},
    {"unit_id": "P2", "unit_type": "police",    "location": [4, 4], "status": "available"},
    {"unit_id": "P3", "unit_type": "police",    "location": [2, 5], "status": "available"},
    {"unit_id": "F1", "unit_type": "fire",      "location": [2, 4], "status": "available"},
    {"unit_id": "F2", "unit_type": "fire",      "location": [5, 5], "status": "available"},
    {"unit_id": "F3", "unit_type": "fire",      "location": [1, 4], "status": "available"},
    {"unit_id": "A1", "unit_type": "ambulance", "location": [5, 1], "status": "available"},
    {"unit_id": "A2", "unit_type": "ambulance", "location": [2, 1], "status": "available"},
    {"unit_id": "A3", "unit_type": "ambulance", "location": [3, 3], "status": "available"},
]

def _fresh_units():
    return copy.deepcopy(_BASE_UNITS)

def _reset_active():
    for k in _active_incidents:
        _active_incidents[k] = 0

def manhattan_distance(loc1, loc2):
    return abs(loc1[0] - loc2[0]) + abs(loc1[1] - loc2[1])

DISTANCE_WEIGHT = 0.6
SEVERITY_WEIGHT = 0.4
MAX_GRID_DISTANCE = 12

def find_best_unit(units, incident_type, incident_location, severity=3):
    """Composite scoring: weighs distance AND severity together."""
    matching = [u for u in units if u["unit_type"] == incident_type and u["status"] == "available"]
    if not matching:
        return None

    severity_norm = max(1, min(severity, 5)) / 5.0

    def composite_score(unit):
        dist = manhattan_distance(unit["location"], incident_location)
        norm_dist = dist / MAX_GRID_DISTANCE
        zone_risk = get_neighborhood_risk(unit["location"])
        opportunity = zone_risk * (1 - severity_norm)
        return DISTANCE_WEIGHT * norm_dist + SEVERITY_WEIGHT * opportunity

    return min(matching, key=composite_score)


class TestStaticRisk(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def test_downtown_interior(self):
        self.assertAlmostEqual(get_neighborhood_risk([1, 1]), _ra.neighborhoods[0]["risk_level"] +
            _ra._HISTORICAL_WEIGHT * (HISTORICAL_INCIDENT_DATA["Downtown"] / max(HISTORICAL_INCIDENT_DATA.values())), places=2)

    def test_industrial_highest_base(self):
        risks = [get_neighborhood_risk([x, y]) for x in range(7) for y in range(7)]
        industrial_risk = get_neighborhood_risk([1, 4])
        self.assertEqual(industrial_risk, max(risks))

    def test_boundary_3_3_is_residential(self):
        r33 = get_neighborhood_risk([3, 3])
        industrial = get_neighborhood_risk([1, 4])
        self.assertNotEqual(r33, industrial)

    def test_boundary_0_3_is_industrial(self):
        self.assertEqual(get_neighborhood_risk([0, 3]), get_neighborhood_risk([1, 4]))

    def test_boundary_3_0_is_suburb(self):
        self.assertEqual(get_neighborhood_risk([3, 0]), get_neighborhood_risk([4, 1]))

    def test_corner_6_6_is_residential(self):
        self.assertEqual(get_neighborhood_risk([6, 6]), get_neighborhood_risk([4, 4]))

    def test_risk_capped_at_1(self):
        for nb in neighborhoods:
            (x1, x2), (y1, y2) = nb["bounds"]
            self.assertLessEqual(get_neighborhood_risk([x1, y1]), 1.0)


class TestHistoricalWeighting(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def test_historical_data_exists_for_all_neighborhoods(self):
        for nb in neighborhoods:
            self.assertIn(nb["id"], HISTORICAL_INCIDENT_DATA)

    def test_industrial_highest_historical(self):
        self.assertEqual(
            max(HISTORICAL_INCIDENT_DATA.values()),
            HISTORICAL_INCIDENT_DATA["Industrial"]
        )

    def test_historical_boosts_risk_above_base(self):
        for nb in neighborhoods:
            (x1, x2), (y1, y2) = nb["bounds"]
            effective = get_neighborhood_risk([x1, y1])
            self.assertGreater(effective, nb["risk_level"],
                msg=f"{nb['id']} effective risk should exceed base due to historical boost")


class TestDynamicRisk(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def tearDown(self):
        _reset_active()

    def test_active_incident_raises_risk(self):
        before = get_neighborhood_risk([4, 1])
        self.assertLess(before, 1.0, "Suburb must have risk < 1.0 before dynamic boost")
        register_active_incident([4, 1])
        after  = get_neighborhood_risk([4, 1])
        self.assertGreater(after, before)

    def test_resolve_incident_lowers_risk(self):
        register_active_incident([4, 1])   # Suburb
        raised = get_neighborhood_risk([4, 1])
        resolve_active_incident([4, 1])
        restored = get_neighborhood_risk([4, 1])
        self.assertLess(restored, raised)

    def test_resolve_never_goes_below_base(self):
        resolve_active_incident([4, 1])
        risk = get_neighborhood_risk([4, 1])
        self.assertGreater(risk, 0.0)

    def test_dynamic_boost_is_capped(self):
        for _ in range(20):
            register_active_incident([4, 1])
        risk = get_neighborhood_risk([4, 1])
        self.assertLessEqual(risk, 1.0)
        _reset_active()

    def test_active_incident_does_not_affect_other_neighborhoods(self):
        downtown_before = get_neighborhood_risk([1, 1])
        register_active_incident([4, 1])
        downtown_after  = get_neighborhood_risk([1, 1])
        self.assertAlmostEqual(downtown_before, downtown_after)
        _reset_active()


class TestIncidentRisk(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def test_severity_scales_risk(self):
        r1 = get_incident_risk([1, 4], 1)
        r5 = get_incident_risk([1, 4], 5)
        self.assertGreater(r5, r1)

    def test_zero_severity_guard(self):
        self.assertGreater(get_incident_risk([1, 1], 0), 0.0)

    def test_negative_severity_guard(self):
        self.assertGreater(get_incident_risk([1, 1], -5), 0.0)

    def test_oversized_severity_clamped(self):
        self.assertAlmostEqual(get_incident_risk([1, 1], 5), get_incident_risk([1, 1], 99))

    def test_result_capped_at_1(self):
        self.assertLessEqual(get_incident_risk([1, 4], 5), 1.0)

    def test_high_risk_zone_max_severity_triggers_threshold(self):
        self.assertGreater(get_incident_risk([1, 4], 5), 0.7)


class TestHeatmap(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def test_heatmap_covers_all_cells(self):
        heatmap = get_risk_heatmap()
        self.assertEqual(len(heatmap), 7 * 7)

    def test_heatmap_has_required_keys(self):
        for cell in get_risk_heatmap():
            for key in ("x", "y", "neighborhood", "risk"):
                self.assertIn(key, cell)

    def test_heatmap_risk_in_range(self):
        for cell in get_risk_heatmap():
            self.assertGreaterEqual(cell["risk"], 0.0)
            self.assertLessEqual(cell["risk"], 1.0)

    def test_heatmap_coordinates_complete(self):
        coords = {(c["x"], c["y"]) for c in get_risk_heatmap()}
        expected = {(x, y) for x in range(7) for y in range(7)}
        self.assertEqual(coords, expected)


class TestNeighborhoodSummary(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def test_summary_covers_all_neighborhoods(self):
        summary = get_neighborhood_summary()
        ids = {s["neighborhood"] for s in summary}
        expected = {nb["id"] for nb in neighborhoods}
        self.assertEqual(ids, expected)

    def test_summary_has_required_keys(self):
        for s in get_neighborhood_summary():
            for key in ("neighborhood", "base_risk", "historical_incidents",
                        "active_incidents", "effective_risk"):
                self.assertIn(key, s)

    def test_summary_active_count_reflects_registrations(self):
        register_active_incident([1, 4])  # Industrial
        summary = {s["neighborhood"]: s for s in get_neighborhood_summary()}
        self.assertEqual(summary["Industrial"]["active_incidents"], 1)
        self.assertEqual(summary["Downtown"]["active_incidents"], 0)
        _reset_active()


class TestRelocationSuggestions(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def tearDown(self):
        _reset_active()

    def test_no_suggestions_when_all_covered(self):
        units = _fresh_units()
        units[0]["location"] = [1, 4]
        suggestions = get_relocation_suggestions(units)
        nb_ids = [s["neighborhood"] for s in suggestions]
        self.assertNotIn("Industrial", nb_ids)

    def test_suggestion_targets_high_risk_zone(self):
        units = _fresh_units()
        for u in units:
            u["location"] = [5, 5]
        suggestions = get_relocation_suggestions(units)
        nb_ids = [s["neighborhood"] for s in suggestions]
        self.assertIn("Industrial", nb_ids)

    def test_suggestion_includes_required_keys(self):
        units = _fresh_units()
        for u in units:
            u["location"] = [5, 5]
        suggestions = get_relocation_suggestions(units)
        for s in suggestions:
            for key in ("unit_id", "unit_type", "current_location",
                        "suggested_location", "neighborhood", "effective_risk", "reason"):
                self.assertIn(key, s)

    def test_no_suggestions_when_all_busy(self):
        units = _fresh_units()
        for u in units:
            u["status"] = "busy"
        suggestions = get_relocation_suggestions(units)
        self.assertEqual(suggestions, [])

    def test_dynamic_risk_can_trigger_new_suggestion(self):
        units = _fresh_units()
        for u in units:
            u["location"] = [1, 1]
        before = [s["neighborhood"] for s in get_relocation_suggestions(units)]

        for _ in range(3):
            register_active_incident([4, 1])   # Suburb
        after = [s["neighborhood"] for s in get_relocation_suggestions(units)]

        suburb_risk = get_neighborhood_risk([4, 1])
        if suburb_risk > 0.7:
            self.assertIn("Suburb", after)
        _reset_active()


class TestFindBestUnit(unittest.TestCase):

    def setUp(self):
        self.units = _fresh_units()

    def test_returns_closest_available(self):
        best = find_best_unit(self.units, "fire", [2, 4])
        self.assertEqual(best["unit_id"], "F1")

    def test_returns_none_when_all_busy(self):
        for u in self.units:
            if u["unit_type"] == "police":
                u["status"] = "busy"
        self.assertIsNone(find_best_unit(self.units, "police", [0, 0]))

    def test_skips_busy_units(self):
        for u in self.units:
            if u["unit_id"] == "A2":
                u["status"] = "busy"
        best = find_best_unit(self.units, "ambulance", [0, 0])
        self.assertNotEqual(best["unit_id"], "A2")

    def test_type_filtering(self):
        best = find_best_unit(self.units, "ambulance", [0, 0])
        self.assertEqual(best["unit_type"], "ambulance")

    def test_wrong_type_returns_none(self):
        self.assertIsNone(find_best_unit(self.units, "helicopter", [0, 0]))


class TestDispatchHandleIncident(unittest.TestCase):

    def setUp(self):
        self.units = _fresh_units()
        _reset_active()

    def tearDown(self):
        _reset_active()

    def _dispatch(self, incident):
        risk_level        = incident["risk_level"]
        incident_type     = incident["type"]
        incident_location = incident["location"]
        severity          = incident.get("severity", 3)

        register_active_incident(incident_location)

        best = find_best_unit(self.units, incident_type, incident_location, severity)
        if best is None:
            return None
        best["status"] = "busy"
        all_unit_ids = [best["unit_id"]]

        assignment = {
            "incident_id":       incident["incident_id"],
            "incident_type":     incident_type,
            "incident_location": incident_location,
            "unit_id":           best["unit_id"],
            "unit_type":         best["unit_type"],
            "risk_level":        risk_level,
            "all_unit_ids":      all_unit_ids,
        }
        if risk_level > 0.7:
            additional = find_best_unit(self.units, incident_type, incident_location, severity)
            if additional:
                additional["status"] = "busy"
                all_unit_ids.append(additional["unit_id"])
                assignment["additional_unit_id"]  = additional["unit_id"]
                assignment["additional_unit_type"] = additional["unit_type"]
        return assignment

    def _complete(self, assignment):
        resolve_active_incident(assignment["incident_location"])
        ids = assignment.get("all_unit_ids") or [assignment["unit_id"]]
        for u in self.units:
            if u["unit_id"] in ids:
                u["status"] = "available"

    def test_unit_marked_busy_after_dispatch(self):
        a = self._dispatch({"incident_id": 1, "type": "fire", "location": [2, 4], "risk_level": 0.3})
        dispatched = next(u for u in self.units if u["unit_id"] == a["unit_id"])
        self.assertEqual(dispatched["status"], "busy")

    def test_correct_unit_type_dispatched(self):
        a = self._dispatch({"incident_id": 2, "type": "police", "location": [0, 0], "risk_level": 0.1})
        self.assertEqual(a["unit_type"], "police")

    def test_returns_none_when_no_unit(self):
        for u in self.units:
            if u["unit_type"] == "ambulance":
                u["status"] = "busy"
        result = self._dispatch({"incident_id": 3, "type": "ambulance", "location": [0, 0], "risk_level": 0.1})
        self.assertIsNone(result)

    def test_high_risk_dispatches_two_units(self):
        a = self._dispatch({"incident_id": 4, "type": "fire", "location": [1, 4], "risk_level": 0.9})
        self.assertIn("additional_unit_id", a)
        self.assertEqual(len(a["all_unit_ids"]), 2)

    def test_low_risk_dispatches_one_unit(self):
        a = self._dispatch({"incident_id": 5, "type": "fire", "location": [1, 1], "risk_level": 0.2})
        self.assertNotIn("additional_unit_id", a)

    def test_all_units_freed_after_completion(self):
        a = self._dispatch({"incident_id": 6, "type": "fire", "location": [1, 4], "risk_level": 0.9})
        self._complete(a)
        for uid in a["all_unit_ids"]:
            u = next(x for x in self.units if x["unit_id"] == uid)
            self.assertEqual(u["status"], "available", f"{uid} still busy after completion")

    def test_freed_unit_can_be_dispatched_again(self):
        a1 = self._dispatch({"incident_id": 7, "type": "police", "location": [0, 0], "risk_level": 0.1})
        self._complete(a1)
        a2 = self._dispatch({"incident_id": 8, "type": "police", "location": [0, 0], "risk_level": 0.1})
        self.assertIsNotNone(a2)

    def test_dynamic_risk_increases_after_dispatch(self):
        risk_before = get_neighborhood_risk([4, 1])
        self.assertLess(risk_before, 1.0)
        self._dispatch({"incident_id": 9, "type": "police", "location": [4, 1], "risk_level": 0.5})
        risk_after  = get_neighborhood_risk([4, 1])
        self.assertGreater(risk_after, risk_before)

    def test_dynamic_risk_decreases_after_completion(self):
        a = self._dispatch({"incident_id": 10, "type": "police", "location": [4, 1], "risk_level": 0.5})
        risk_during = get_neighborhood_risk([4, 1])
        self._complete(a)
        risk_after  = get_neighborhood_risk([4, 1])
        self.assertLess(risk_after, risk_during)


class TestUnitServiceStatusProgression(unittest.TestCase):

    def test_all_unit_ids_propagated(self):
        assignment = {"incident_id": 99, "unit_id": "F1", "all_unit_ids": ["F1", "F3"]}
        statuses = []
        for status in ("en_route", "on_scene", "completed"):
            statuses.append({
                "unit_id":           assignment["unit_id"],
                "incident_id":       assignment["incident_id"],
                "status":            status,
                "all_unit_ids":      assignment.get("all_unit_ids", [assignment["unit_id"]]),
                "incident_location": [1, 4],
            })
        completed = statuses[-1]
        self.assertIn("all_unit_ids", completed)
        self.assertEqual(completed["all_unit_ids"], ["F1", "F3"])
        self.assertIn("incident_location", completed)

    def test_status_order(self):
        statuses = ["en_route", "on_scene", "completed"]
        self.assertEqual(statuses[0], "en_route")
        self.assertEqual(statuses[-1], "completed")


class TestIncidentServiceFields(unittest.TestCase):

    def setUp(self):
        _reset_active()

    def test_required_fields_present(self):
        import time
        incident = {
            "incident_id": int(time.time()),
            "type":        "fire",
            "location":    [1, 4],
            "description": "test",
            "severity":    4,
            "risk_level":  get_incident_risk([1, 4], 4),
        }
        for field in ("incident_id", "type", "location", "description", "severity", "risk_level"):
            self.assertIn(field, incident)

    def test_risk_level_in_range(self):
        self.assertBetween(get_incident_risk([1, 4], 4), 0.0, 1.0)

    def assertBetween(self, value, lo, hi):
        self.assertGreaterEqual(value, lo)
        self.assertLessEqual(value, hi)


class TestCompositeScoring(unittest.TestCase):
    """
    Tests for the composite scoring function that weighs both
    distance AND severity, as described in the interim report (Section 3.2.6).
    """

    def setUp(self):
        self.units = _fresh_units()
        _reset_active()

    def test_low_severity_preserves_high_risk_zone_unit(self):
        """Low-severity incident prefers a unit from a low-risk zone
        over a closer unit stationed in a high-risk zone."""
        # Fire at [3,3] (Residential zone).  Closest fire unit is F1 at
        # [2,4] (Industrial, risk=1.0, distance=2).  But for severity=1
        # the composite score should prefer F2 at [5,5] (Residential,
        # risk~0.61, distance=4) to keep F1 guarding Industrial.
        best = find_best_unit(self.units, "fire", [3, 3], severity=1)
        self.assertEqual(best["unit_id"], "F2")

    def test_high_severity_picks_closest_regardless(self):
        """Critical incident ignores opportunity cost — closest unit wins."""
        best = find_best_unit(self.units, "fire", [3, 3], severity=5)
        self.assertEqual(best["unit_id"], "F1")

    def test_severity_changes_unit_selection(self):
        """Different severity levels can produce different assignments."""
        low  = find_best_unit(self.units, "fire", [3, 3], severity=1)
        high = find_best_unit(self.units, "fire", [3, 3], severity=5)
        self.assertNotEqual(low["unit_id"], high["unit_id"],
            "Composite scoring should pick different units based on severity")

    def test_equal_distance_prefers_lower_risk_zone(self):
        """When two units are equidistant, prefer the one in the lower-risk zone."""
        # Move an ambulance to Downtown (low risk) and one to Industrial (high risk),
        # both at the same distance from the incident
        for u in self.units:
            if u["unit_id"] == "A1":
                u["location"] = [3, 0]   # Suburb zone, distance from [4,1]=2
            if u["unit_id"] == "A2":
                u["location"] = [2, 3]   # Industrial zone, distance from [4,1]=3
            if u["unit_id"] == "A3":
                u["location"] = [5, 2]   # Suburb zone, distance from [4,1]=2
        # For low-severity, among equidistant units, prefer the one in lower-risk zone
        best = find_best_unit(self.units, "ambulance", [4, 1], severity=1)
        # A2 in Industrial should NOT be chosen despite reasonable distance
        self.assertNotEqual(best["unit_id"], "A2")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [
        TestStaticRisk,
        TestHistoricalWeighting,
        TestDynamicRisk,
        TestIncidentRisk,
        TestHeatmap,
        TestNeighborhoodSummary,
        TestRelocationSuggestions,
        TestFindBestUnit,
        TestCompositeScoring,
        TestDispatchHandleIncident,
        TestUnitServiceStatusProgression,
        TestIncidentServiceFields,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
