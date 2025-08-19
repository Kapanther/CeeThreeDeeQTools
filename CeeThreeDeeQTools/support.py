import os
from pathlib import Path

ctdgroup_info = {
    1: {"group": "Projects", "group_id": "projects"},
    2: {"group": "Hydrology", "group_id": "hydrology"},
    3: {"group": "3D", "group_id": "3d"}
}
ctdtool_info = {    
    "ExportProjectStylesAsXML": {
        "disp": "Export Project Styles as XML",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"]
    },
    "ExportDataSourcesMap": {
        "disp": "Export Data Sources Map",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"]
    },
    "GenerateCatchmentsMinArea": {
        "disp": "Generate Catchments with Minimum Area",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"]
    }
}
ctdpaths = {  
    "img": f"{Path(os.path.split(os.path.split(os.path.dirname(__file__))[0])[0]).as_posix()}/assets/img/"
}