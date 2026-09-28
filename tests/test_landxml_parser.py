import math

from CeeThreeDeeQTools.Tools.LandXMLImport.ctdq_LandXMLImportParser import (
    LandXMLParser,
)


def test_scan_structure_discovers_file_contents(minimal_landxml_path):
    structure = LandXMLParser.scan_structure(str(minimal_landxml_path))

    assert structure.units == "Metric"
    assert structure.application == "Autodesk Civil 3D"
    assert structure.project.endswith("LANDXMLimport.dwg")
    assert [item["name"] for item in structure.alignments] == [
        "CenterLineWithSpiralTest", "OffsetAlignmentTest", "StraightLineTest"
    ]
    assert structure.alignments[0]["profiles"] == [
        {"name": "SurveyTest", "kind": "surf"},
        {"name": "ProfileTest", "kind": "align"},
    ]
    assert structure.alignments[2]["profiles"] == [
        {"name": "ProfileSurfaceTest", "kind": "surf"},
        {"name": "StraightLineTest_layoutProfileTest", "kind": "align"},
    ]
    assert [item["name"] for item in structure.surfaces] == ["SurfaceTest"]
    assert [item["name"] for item in structure.pipe_networks] == [
        "Pipes", "PipesAndStructures"
    ]
    assert structure.corridors == [{
        "name": "CorridorTest",
        "alignment_refs": ["CenterLineWithSpiralTest"],
    }]
    assert [item["count"] for item in structure.point_groups] == [15, 7, 8]
    assert [item["name"] for item in structure.point_groups] == [
        "(all points)", "PointGroup01Test", "PointGroup02Test"
    ]


def test_parse_points_resolves_group_references_and_coordinate_order(
    minimal_landxml_path,
):
    warnings = []
    points = LandXMLParser.parse_points(
        str(minimal_landxml_path), ["PointGroup01Test"], warnings
    )

    assert warnings == []
    assert len(points) == 7
    assert points[0]["number"] == "9"
    assert points[0]["code"] == "BOREHOLE"
    assert points[0]["x"] == 501832.30266683694
    assert points[0]["y"] == 6954402.050394769
    assert points[0]["z"] == 0.0
    assert all(point["groups"] == "PointGroup01Test" for point in points)


def test_parse_alignment_densifies_clothoid_spiral(minimal_landxml_path):
    alignments = LandXMLParser.parse_alignments(
        str(minimal_landxml_path), ["CenterLineWithSpiralTest"],
        curve_tolerance=0.01,
    )

    alignment = alignments[0]
    points = alignment["points"]
    spiral_start = (501792.4007629139, 6954346.40557661)
    spiral_end = (501793.4941965435, 6954341.576782009)
    start_index = points.index(spiral_start)
    end_index = points.index(spiral_end)

    assert end_index - start_index >= 8
    assert alignment["warnings"] == []

    first_spiral_segment = (
        points[start_index + 1][0] - points[start_index][0],
        points[start_index + 1][1] - points[start_index][1],
    )
    spiral_heading = math.degrees(math.atan2(
        first_spiral_segment[1], first_spiral_segment[0]))
    assert math.isclose(spiral_heading, -86.2039724, abs_tol=0.5)


def test_parse_corridor_cross_section_links(minimal_landxml_path):
    corridors = LandXMLParser.parse_corridors(
        str(minimal_landxml_path), ["CorridorTest"]
    )
    assert corridors[0]["alignment_refs"] == ["CenterLineWithSpiralTest"]

    alignment = LandXMLParser.parse_alignments(
        str(minimal_landxml_path), ["CenterLineWithSpiralTest"]
    )[0]
    sections = alignment["cross_sections"]
    assert len(sections) == 15
    first_link = sections[0]["links"][0]
    assert sections[0]["station"] == 0.0
    assert first_link == {
        "code": "Top",
        "start_offset_x": 0.0,
        "start_offset_y": 0.0,
        "end_offset_x": -2.0,
        "end_offset_y": -0.04,
        "grade": 2.0,
        "start_code": "",
        "end_code": "P2",
    }


def test_parse_surface_preserves_visible_and_hidden_faces(minimal_landxml_path):
    surfaces = LandXMLParser.parse_surfaces(
        str(minimal_landxml_path), ["SurfaceTest"]
    )

    assert len(surfaces) == 1
    surface = surfaces[0]
    assert surface["description"] == "Description"
    assert surface["points"]["5"] == (
        501801.5108059272, 6954332.986641983, 16.649999999907
    )
    assert len(surface["points"]) == 16
    assert len(surface["faces"]) == 14
    assert len(surface["hidden_faces"]) == 6
    assert ("7", "6", "5") in surface["faces"]
    assert ("20", "5", "19") in surface["hidden_faces"]


def test_parse_feature_lines_preserves_groups_and_3d_vertices(minimal_landxml_path):
    feature_groups = LandXMLParser.parse_feature_lines(
        str(minimal_landxml_path), ["Siteless FeatureLines"]
    )

    assert len(feature_groups) == 1
    group = feature_groups[0]
    assert group["name"] == "Siteless FeatureLines"
    assert len(group["features"]) == 2
    feature = group["features"][0]
    assert feature["name"] == "NoSiteFeatureLine1Test"
    assert len(feature["points"]) == 4
    assert feature["points"][0] == (
        501777.88286035182, 6954322.229089018, 0.0
    )
    assert feature["code"] == "FeatureLine"


def test_parse_parcels_closes_boundary_and_preserves_area(minimal_landxml_path):
    parcels = LandXMLParser.parse_parcels(
        str(minimal_landxml_path), ["Basic : 1"]
    )

    assert len(parcels) == 1
    parcel = parcels[0]
    assert parcel["name"] == "Basic : 1"
    assert parcel["area"] == 431.924262827484
    assert len(parcel["points"]) == 5
    assert parcel["points"][0] == parcel["points"][-1]
    assert parcel["points"][0][2] == 0.0


def test_parse_pipe_networks_keeps_null_endpoints_but_hides_them(
    minimal_landxml_path,
):
    networks = LandXMLParser.parse_pipe_networks(
        str(minimal_landxml_path), ["Pipes"]
    )

    assert len(networks) == 1
    network = networks[0]
    assert network["type"] == "storm"
    assert len(network["pipes"]) == 3
    assert len(network["structures"]) == 0
    assert "StartNullStruct3" in network["structure_lookup"]
    assert not network["structure_lookup"]["StartNullStruct3"]["visible"]

    pipes = {pipe["name"]: pipe for pipe in network["pipes"]}
    assert pipes["Pipe - (6) (Pipes)"]["type"] == "CircPipe"
    assert pipes["Pipe - (6) (Pipes)"]["dimensions"]["diameter"] == 100.0
    assert all(pipe["type"] == "CircPipe" for pipe in pipes.values())

    assert set(network["structure_lookup"]) == {
        "StartNullStruct3", "EndNullStruct3", "StartNullStruct4",
        "EndNullStruct4", "StartNullStruct5", "EndNullStruct5",
    }


def test_parse_pipe_network_selection_filters_networks(minimal_landxml_path):
    networks = LandXMLParser.parse_pipe_networks(
        str(minimal_landxml_path), ["PipesAndStructures"]
    )

    assert [network["name"] for network in networks] == ["PipesAndStructures"]
    network = networks[0]
    assert len(network["structures"]) == 5
    assert len(network["pipes"]) == 3
    structures = {item["name"]: item for item in network["structures"]}
    assert set(item["type"] for item in structures.values()) == {
        "RectStruct", "OutletStruct", "CircStruct"
    }
    assert structures["Structure - (3) (PipesAndStructures)"]["dimensions"][
        "diameter"
    ] == 1200.0
    pipes = {pipe["name"]: pipe for pipe in network["pipes"]}
    assert pipes["Pipe - (1) (PipesAndStructures)"]["type"] == "RectPipe"
    assert pipes["Pipe - (1) (PipesAndStructures)"]["dimensions"]["height"] == 0.5
    inverts = network["structure_lookup"][
        "Structure - (4) (PipesAndStructures)"
    ]["invert_records"]
    assert {record["ref_pipe"]: record["elev"] for record in inverts} == {
        "Pipe - (2) (PipesAndStructures)": -0.05,
        "Pipe - (3) (PipesAndStructures)": -0.05,
    }
