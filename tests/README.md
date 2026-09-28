# Tests

## Scope

The default suite runs outside QGIS. It currently covers:

- LandXML parsing in `CeeThreeDeeQTools/Tools/LandXMLImport/ctdq_LandXMLImportParser.py`
- Vertical-profile math in `ctdq_LandXMLVerticalProfile.py`
- Small isolated UI/service behaviors that can run with test doubles

The Civil 3D sample at `tests/fixtures/landxml_minimal.xml` is the shared
fixture for LandXML tests. Despite its filename, it is a realistic export and
contains alignments, profiles, spirals, points, surfaces, pipe networks,
corridors, cross sections, feature lines, and parcels.

## Setup and Commands

Run these commands from the repository root:

```text
python -m pip install -r requirements-dev.txt
python -m pytest
python -m pytest -q
python -m pytest tests/test_landxml_parser.py -q
python -m pytest --cov --cov-report=term-missing
```

`pyproject.toml` limits discovery to `tests/` and files named `test_*.py`.
GitHub Actions runs the coverage command on Python 3.11 and 3.12. The local
QGIS Python interpreter is useful when a test imports QGIS modules:

```text
"C:\\Program Files\\QGIS 3.44.13\\bin\\python.exe" -m pytest -q
```

## Writing Parser Tests

Use the `minimal_landxml_path` fixture from `tests/conftest.py` and pass its
string path to parser methods. Keep parser tests independent of QGIS so they
also run in GitHub Actions.

Prefer assertions about the public returned data rather than XML internals:

```python
def test_parse_corridor_links(minimal_landxml_path):
		alignments = LandXMLParser.parse_alignments(
				str(minimal_landxml_path), ["CenterLineWithSpiralTest"]
		)

		sections = alignments[0]["cross_sections"]
		assert sections[0]["station"] == 0.0
		assert sections[0]["links"][0]["end_code"] == "P2"
```

For each new parser object, cover at least:

1. Discovery in `scan_structure()`.
2. Selection filtering with `wanted_names` or equivalent.
3. A representative geometry or numeric value.
4. Metadata and edge behavior, such as missing names, empty codes, closure,
	 hidden faces, null endpoints, or broken references.

Use `math.isclose()` for calculated floating-point values. LandXML coordinate
text is stored as northing/easting and parser results use `(x=easting,
y=northing[, z])`.

## Writing Logic and QGIS Tests

Layer creation and dialog behavior depend on QGIS APIs and are not part of the
default CI suite. For those tests:

- Run with the QGIS Python interpreter shown above, or provide focused mocks
	matching the existing test style.
- Test the parser separately first; do not duplicate XML parsing assertions in
	layer tests.
- Assert layer geometry type, feature count, field names, attributes, CRS, and
	group placement.
- Preserve existing user changes in the shared fixture. Add a smaller fixture
	only when the behavior cannot be expressed clearly with the sample.

## Test Workflow for Changes

1. Identify the owning parser, logic, or dialog method.
2. Add a focused regression test beside the nearest existing test.
3. Run that test file with `python -m pytest tests/<file> -q`.
4. Implement the smallest change that makes it pass.
5. Run `python -m pytest -q` and then the coverage command.
6. For QGIS-facing changes, run `py_compile`, import the touched modules with
	 the QGIS interpreter, and deploy with `Debug-Local.bat` for manual testing.

Tests are not included in release packages. See `.github/workflows/tests.yml`
for the authoritative CI command and Python versions.
