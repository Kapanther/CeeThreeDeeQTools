import os
from pathlib import Path

ctdgroup_info = {
    1: {"group": "Projects", "group_id": "projects"},
    2: {"group": "Hydrology", "group_id": "hydrology"},
    3: {"group": "3D", "group_id": "3d"}
}

fop = '<font style="color:#CD5C5C;">' #font style for parameters (redish color)
foe = '<font style="color:#9400D3;">' #font style for emphasis (purple)
fcc = "</font>"                       #font style end

ctdprocessing_info = {    
    "ExportProjectLayerStyles": {
        "disp": "Export Project Layer Styles",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"],
        "shortHelp": (
            "Exports the styles of all layers in the current QGIS project to a xml file and/or a directory of QML files that can be read in by other projects."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Output XML file:{fcc} Location to save XML file detailing styles details.</li>"
            f"<li>{fop}Output Directory for QMLS:{fcc} The directory where the layer QML files will be saved. If ByTheme is selected directories for each theme will be created in this location</li>"
            "</ul>"
        )
    },
    "ExportDataSourcesMap": {
        "disp": "Export Data Sources Map",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"],
        "shortHelp": (
            "Generates a bounding box map of all layers used in the current QGIS project, each bounding box will contain details about the layer including path,CRS etc."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Output Bounding Box File:{fcc} The file where the data sources map will be saved.</li>"
            "</ul>"
        )
    },
    "GenerateCatchmentsMinArea": {
        "disp": "Generate Catchments with Minimum Area",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "Creates vector based catchment areas and streams from just a raster, to prevent creating small granular catchments a minimum area is specified start with about 15000 units. This minimum area is based on the pixels of the raster ."
            "NOTE: This tool utilised Grass GIS algorithms that are typically packaged with QGIS but may require additional installation steps depending on your OS."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input Raster:{fcc} The raster representing ground surface.</li>"
            f"<li>{fop}Minimum Area:{fcc} The minimum area for each catchment (in square units, raster pixels).</li>"
            f"<li>{fop}Output Streams:{fcc} The file where the generated vector streams will be saved.</li>"
            f"<li>{fop}Output Catchments:{fcc} The file where the generated vector catchments will be saved.</li>"
            "</ul>"
        )
    },
    "FindRasterPonds": {
        "disp": "Find Raster Ponds",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "Detects ponds (sinks) in a raster and outputs a vector layer with polygons representing the ponds."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input Raster:{fcc} The raster representing ground surface.</li>"
            f"<li>{fop}Minimum Pond Size (in Square Units):{fcc} The minimum size for each pond (in square units of the CRS).</li>"
            f"<li>{fop}Smooth Pond Outlines:{fcc} Whether to smooth the pond outlines after detection (recommended removes the squares).</li>"
            f"<li>{fop}Output Ponds:{fcc} The file where the generated vector ponds will be saved.</li>"
            f"<li>{fop}Output Filled Raster [optional]:{fcc} The file where the output filled raster will be saved.</li>"
            f"<li>{fop}Output Pond Depth Raster [optional]:{fcc} The file where the output pond depth raster will be saved.</li>"
            f"<li>{fop}Output Pond Depth Raster (Valid) [optional]:{fcc} The file where the output pond depth raster (valid) will be saved.</li>"

            "</ul>"
        )
    },
    "CalculateStageStoragePond": {
        "disp": "Calculate Stage Storage for Ponds",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "Calculates the stage-storage relationship for pond polygons based on a ground raster. The output is a vector layer with overlapping polygons representing slices of the pond at different stages, each with attributes for area and volume."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input Ponds Vector Layer:{fcc} The vector layer containing pond polygons.</li>"
            f"<li>{fop}Input Ground Raster:{fcc} The raster representing ground surface.</li>"
            f"<li>{fop}Output Stage Storage Slices:{fcc} The file where the output stage storage slices will be saved.</li>"
            "</ul>"
        )
    }

}

def get_plugin_dir():
    """
    Returns the plugin directory. This function should be called with
    self.plugin_dir from the provider or plugin class.
    """
    return os.path.dirname(os.path.dirname(__file__))

ctdpaths = {  
    "img": os.path.join(get_plugin_dir(), "assets", "img")
}