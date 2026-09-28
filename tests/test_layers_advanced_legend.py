from unittest.mock import MagicMock

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsLineSymbol, QgsProject, QgsSingleSymbolRenderer, QgsVectorLayer

from CeeThreeDeeQTools.Tools.LayersAdvanced.LayersAdvancedDialog import LayersAdvancedDialog


def test_vector_style_preview_updates_when_renderer_changes():
    app = QApplication.instance() or QApplication([])
    project = QgsProject.instance()
    project.clear()
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "Preview", "memory")
    assert layer.isValid()
    layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"line_color": "255,0,0,255"})))
    project.addMapLayer(layer)

    dialog = LayersAdvancedDialog(MagicMock())
    try:
        item = dialog._find_layer_item(layer.id())
        assert item is not None
        assert dialog.layer_tree.iconSize().width() == 32
        assert item.childCount() == 1
        assert item.child(0).text(0) == layer.name()
        red_preview = item.child(0).icon(0).pixmap(32, 20).toImage()
        assert not red_preview.isNull()

        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"line_color": "0,0,255,255"})))
        item = dialog._find_layer_item(layer.id())
        assert item.childCount() == 1
        blue_preview = item.child(0).icon(0).pixmap(32, 20).toImage()
        assert red_preview != blue_preview

        dialog.hide_all_layers()
        assert item.child(0).data(0, Qt.ItemDataRole.CheckStateRole) is None
    finally:
        dialog.close()
        project.clear()