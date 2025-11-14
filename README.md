# CeeThreeDeeQTools
A compact suite of QGIS processing utilities designed for civil and geospatial engineers, drafters, and GIS analysts. These tools automate repetitive tasks, help manage and transfer layer styles and data, and support basic terrain and network generation workflows — improving consistency and saving time across projects.

## Processing Tools

- **Export Data Sources Map**: Creates an index vector layer of bounding boxes representing each layer in the current QGIS project; each box includes attributes that document key layer metadata (name, source, CRS, extent, etc.).
- **Export Project Layer Styles**: Exports project layer styles as a single XML or as separate QML files so styles can be re-used or shared. Supports exporting either "By Theme" or "By Layer".
- **Import Project Layer Styles (COMING SOON)**: Imports QML-style libraries exported by the exporter to reapply consistent styling across projects. Supports "By Theme" or "By Layer" workflows.
- **Generate Streams and Catchments**: Produces vector catchments and stream networks from a DEM and a minimum area threshold. Uses GRASS utilities (r.watershed, r.to.vect) and groups connected streams into logical networks.
- **Convert Large 3D DXF/DWG Faces to Points (COMING SOON)**: Converts large 3D face geometries from CAD files into point CSVs for downstream processing, with options for filtering and boundary extraction.
- **Project 2D Section to 3D (COMING SOON)**: Converts 2D plan-section data into true 3D coordinates, with exports available as 3D DXF or 3D shapefiles for use in other applications.

## Custom Tools

- **Project Validation Report**: Compares the current QGIS project layers against an Excel inventory of data sources and flags mismatches or missing files — useful for quality control in large or collaborative projects.
- **Mirror Project Tool**: Synchronizes layers, map themes, and print layouts from a master QGIS project to multiple child projects. Updates data sources, symbology, layer order, and group structure while preserving child-specific settings like layer filters and manually adjusted label positions (auxiliary storage). Ideal for maintaining consistency across multiple related projects or project variants.
- **Package Layer Updater**: Updates layers in geopackage files with data from the active QGIS project. Tracks update history and modification dates, supports both vector and raster layers, and can skip unchanged layers or fix duplicate FID values. Perfect for maintaining synchronized geopackage archives or distributing data updates to field teams.
