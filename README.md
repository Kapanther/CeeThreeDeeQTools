# CeeThreeDeeQTools
QGIS processing tools for Civil/Geo engineers and drafters. 

## Processing Tools

- **Export Data Sources Map**: Create a Index Vector Layer containing bounding boxes that represent each of the layers in the current QGIS project. Each bounding box has attributes containg key information about the layer
- **Export Project Layer Styles**: Export all of your project layers as an XML files or as seperate QML layer styles files that can be read into another project. Options available to export "By Theme" or "By Layer"
- **Import Project Layer Styles (COMING SOON)**: Import all of your project layers afrom a library of QML layer styles files that have been exported from the "Export Project Layer Styles" tool. Options available to import "By Theme" or "By Layer"
- **Generate Catchments - Min Area**: Generates vector catchments and streams with just a DEM and a minimum area. (Utilises basic grass r.watersheds and r.to.vect functions)
- **Convert Large 3D Dxf Faces to Points(CSV) (COMING SOON)**: Process large DWG/DXF files containing large numbers of 3D faces into point files (*.csv), options for filtering and boundary extraction included.
- **Project 2D Section to 3D (COMING SOON)**: Convert 2D plan sections to 3D section data in real space. Result can be exported to 3D dxf or as 3D shp file that can be used in other applications.


## Custom Tools

- **Project Validation Report**: Validates the current QGIS project layers against an excel file containing data sources. Useful for validating files used in larger complex QGIS projects.