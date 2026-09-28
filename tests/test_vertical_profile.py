import math

from CeeThreeDeeQTools.Tools.LandXMLImport.ctdq_LandXMLVerticalProfile import (
    VerticalProfile,
)


def pvi(station, elevation, kind="PVI", **values):
    return {
        "type": kind,
        "station": station,
        "elevation": elevation,
        "length": values.get("length"),
        "length2": values.get("length2"),
        "radius": values.get("radius"),
    }


def test_linear_profile_interpolates_and_rejects_out_of_bounds():
    profile = VerticalProfile([pvi(0, 100), pvi(100, 110)])

    assert profile.is_valid
    assert profile.start_station == 0
    assert profile.end_station == 100
    assert profile.elevation_at(25) == 102.5
    assert profile.elevation_at(-1) is None
    assert profile.elevation_at(101) is None
    assert profile.critical_stations() == [0, 100]


def test_symmetric_parabolic_curve_matches_pvi_elevation():
    profile = VerticalProfile([
        pvi(0, 0),
        pvi(50, 10, "ParaCurve", length=20),
        pvi(100, 15),
    ])

    assert profile.is_valid
    assert len(profile.curves) == 1
    assert profile.curves[0]["kind"] == "para"
    assert math.isclose(profile.elevation_at(50), 9.75)
    assert profile.elevation_at(40) < 10
    assert profile.elevation_at(60) > 10
    assert len(profile.critical_stations(0.01)) > 3


def test_asymmetric_parabolic_curve_is_evaluable():
    profile = VerticalProfile([
        pvi(0, 0),
        pvi(50, 10, "UnsymParaCurve", length=10, length2=30),
        pvi(100, 20),
    ])

    assert len(profile.curves) == 1
    curve = profile.curves[0]
    assert curve["kind"] == "unsym"
    assert math.isclose(profile.elevation_at(curve["start"]), curve["start_elev"])
    assert math.isclose(profile.elevation_at(curve["end"]), curve["end_elev"])


def test_circular_curve_is_evaluable_and_densified():
    profile = VerticalProfile([
        pvi(0, 0),
        pvi(50, 10, "CircCurve", radius=100),
        pvi(100, 15),
    ])

    assert len(profile.curves) == 1
    assert profile.curves[0]["kind"] == "circ"
    assert math.isfinite(profile.elevation_at(50))
    assert len(profile.critical_stations(0.01)) > 3


def test_invalid_profile_has_no_extent_or_elevation():
    profile = VerticalProfile([pvi(10, 2)])

    assert not profile.is_valid
    assert profile.start_station == 10
    assert profile.end_station == 10
    assert profile.elevation_at(10) is None
    assert profile.critical_stations() == []
