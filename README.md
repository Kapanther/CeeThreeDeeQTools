# CeeThreeDeeQTools
QGIS processing tools for Civil/Geo engineers and drafters.
## Processing Tools

- **Export Data Sources Map**: Create a Index Vector Layer containing bounding boxes that represent each of the layers in the current QGIS project. Each bounding box has attributes containg key information about the layer
- **Export Project Layer Styles**: Export all of your project layers as an XML files or as seperate QML layer styles files that can be read into another project. Options available to export "By Theme" or "By Lyaer"
- **Generate Catchments - Min Area**: Generates vector catchments and streams with just a DEM and a minimum area. (Utilises basic grass r.watersheds and r.to.vect functions)

## Custom Tools

- **Project Validation Report**: Validates the current QGIS project against an excel file containing data sources