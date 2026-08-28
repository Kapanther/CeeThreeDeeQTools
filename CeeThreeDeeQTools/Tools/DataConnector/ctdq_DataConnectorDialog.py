"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QApplication,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsMapLayer

from .ctdq_DataConnectorLogic import DataConnectorLogic
from .ctdq_AddConnectedLayerDialog import AddConnectedLayerDialog
from .ctdq_DataConnectorExtract import DataConnectorExtractor
from .ctdq_DataConnectorRefresh import DataConnectorRefresh
from .ctdq_RefreshLayersDialog import RefreshLayersDialog, EXTENT_SOURCE_NEW
from .ctdq_AddRasterLayerDialog import AddRasterLayerDialog
from .ctdq_DataConnectorRasterExtract import DataConnectorRasterExtractor
from .ctdq_DataConnectorRasterRefresh import DataConnectorRasterRefresh
from .ctdq_RasterTileMath import RasterTileMath


COLUMNS = [
    "Layer Name",
    "Geom Type",
    "Source",
    "Service",
    "Source CRS",
    "Target CRS",
    "Last Updated",
]

SOURCE_COLUMN = 2
SOURCE_COLUMN_MAX_WIDTH = 250


class DataConnectorDialog(QDockWidget):
    """Dockable palette listing layers extracted from streaming data sources."""

    def __init__(self, iface, parent=None):
        super().__init__("Data Connector", parent)
        self.iface = iface
        self.setObjectName("CeeThreeDeeQToolsDataConnector")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        main_widget = QWidget()
        self.setWidget(main_widget)
        self.init_ui(main_widget)

        self.connect_project_signals()
        self.refresh_layers()

    # ------------------------------------------------------------------ UI

    def init_ui(self, main_widget):
        layout = QVBoxLayout()

        button_row = QHBoxLayout()
        self.add_layer_button = QPushButton("Add New Vector Layers")
        self.add_layer_button.clicked.connect(self.open_add_connected_layer_dialog)
        button_row.addWidget(self.add_layer_button)

        self.add_raster_button = QPushButton("Add New Raster Layers")
        self.add_raster_button.clicked.connect(self.open_add_raster_layer_dialog)
        button_row.addWidget(self.add_raster_button)

        self.refresh_button = QPushButton("Refresh Vector Layers")
        self.refresh_button.setToolTip(
            "Re-extract every connected vector layer from its original data source."
        )
        self.refresh_button.clicked.connect(self.on_refresh_vectors_clicked)
        button_row.addWidget(self.refresh_button)

        self.refresh_raster_button = QPushButton("Refresh Raster Layers")
        self.refresh_raster_button.setToolTip(
            "Re-extract every connected raster layer from its original tile service."
        )
        self.refresh_raster_button.clicked.connect(self.on_refresh_rasters_clicked)
        button_row.addWidget(self.refresh_raster_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter connected layers...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        self.layer_tree = QTreeWidget()
        self.layer_tree.setColumnCount(len(COLUMNS))
        self.layer_tree.setHeaderLabels(COLUMNS)
        self.layer_tree.setRootIsDecorated(False)
        self.layer_tree.setAlternatingRowColors(True)
        self.layer_tree.setSortingEnabled(True)
        self.layer_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        layout.addWidget(self.layer_tree)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        main_widget.setLayout(layout)

    # --------------------------------------------------------------- signals

    def connect_project_signals(self):
        project = QgsProject.instance()
        project.layersAdded.connect(self.refresh_layers)
        project.layersRemoved.connect(self.refresh_layers)

    def disconnect_project_signals(self):
        project = QgsProject.instance()
        for signal, slot in (
            (project.layersAdded, self.refresh_layers),
            (project.layersRemoved, self.refresh_layers),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def on_refresh_vectors_clicked(self):
        """Confirm, then re-extract every connected vector layer from its stored source."""
        layers = self._connected_layers_by_type(raster=False)
        if not layers:
            QMessageBox.information(
                self, "Data Connector", "There are no connected vector layers to refresh."
            )
            return

        dialog = RefreshLayersDialog(len(layers), self, title="Refresh Vector Layers")
        if not dialog.exec():
            return

        override_geometry = None
        override_crs = None
        clip_to_geometry = False

        if dialog.get_extent_source() == EXTENT_SOURCE_NEW:
            try:
                override_geometry, override_crs, clip_to_geometry = (
                    DataConnectorExtractor.build_extent_geometry(
                        dialog.get_extent_mode(),
                        self.iface,
                        extent_layer=dialog.get_extent_layer(),
                        mask_layer=dialog.get_mask_layer(),
                    )
                )
            except ValueError as exc:
                QMessageBox.warning(self, "Data Connector", str(exc))
                return

        progress, update_progress = self._make_progress(
            "Refreshing vector layers...", "Refresh Vector Layers"
        )

        try:
            results = DataConnectorRefresh.refresh_layers(
                layers,
                override_extent_geometry=override_geometry,
                override_extent_crs=override_crs,
                clip_to_geometry=clip_to_geometry,
                progress_callback=update_progress,
            )
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Data Connector", f"Refresh failed:\n{exc}")
            return
        finally:
            progress.close()

        self._report_results(results, 'refreshed', 'Refreshed')
        self.refresh_layers()

    def on_refresh_rasters_clicked(self):
        """Confirm, then re-render every connected raster layer from its tile service."""
        layers = self._connected_layers_by_type(raster=True)
        if not layers:
            QMessageBox.information(
                self, "Data Connector", "There are no connected raster layers to refresh."
            )
            return

        dialog = RefreshLayersDialog(
            len(layers),
            self,
            title="Refresh Raster Layers",
            show_zoom=True,
            canvas_zoom=RasterTileMath.canvas_zoom(self.iface.mapCanvas()),
        )
        if not dialog.exec():
            return

        override_geometry = None
        override_crs = None

        if dialog.get_extent_source() == EXTENT_SOURCE_NEW:
            try:
                override_geometry, override_crs, _ = (
                    DataConnectorExtractor.build_extent_geometry(
                        dialog.get_extent_mode(),
                        self.iface,
                        extent_layer=dialog.get_extent_layer(),
                        mask_layer=dialog.get_mask_layer(),
                    )
                )
            except ValueError as exc:
                QMessageBox.warning(self, "Data Connector", str(exc))
                return

        progress, update_progress = self._make_progress(
            "Refreshing raster layers...", "Refresh Raster Layers"
        )

        try:
            results = DataConnectorRasterRefresh.refresh_layers(
                layers,
                override_extent_geometry=override_geometry,
                override_extent_crs=override_crs,
                override_zoom=dialog.get_zoom(),
                progress_callback=update_progress,
            )
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Data Connector", f"Refresh failed:\n{exc}")
            return
        finally:
            progress.close()

        self._report_results(results, 'refreshed', 'Refreshed')
        self.refresh_layers()

    def _connected_layers_by_type(self, raster: bool) -> list:
        return [
            layer for layer in DataConnectorLogic.get_connected_layers()
            if (layer.type() == QgsMapLayer.LayerType.RasterLayer) == raster
        ]

    def _make_progress(self, message, title):
        """Create a modal progress dialog and a callback that drives it."""
        progress = QProgressDialog(message, "Cancel", 0, 100, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def update_progress(text, percent):
            progress.setLabelText(text)
            progress.setValue(percent)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise Exception("Operation cancelled by user")

        return progress, update_progress

    # ------------------------------------------------------------ list build

    def refresh_layers(self, *args):
        """Rebuild the list of Data Connector managed layers."""
        self.layer_tree.setSortingEnabled(False)
        self.layer_tree.clear()

        connected_layers = DataConnectorLogic.get_connected_layers()
        for layer in connected_layers:
            self.layer_tree.addTopLevelItem(self._build_item(layer))

        for column in range(len(COLUMNS)):
            self.layer_tree.resizeColumnToContents(column)

        # Service URIs are long enough to push every other column off screen
        if self.layer_tree.columnWidth(SOURCE_COLUMN) > SOURCE_COLUMN_MAX_WIDTH:
            self.layer_tree.setColumnWidth(SOURCE_COLUMN, SOURCE_COLUMN_MAX_WIDTH)

        self.layer_tree.setSortingEnabled(True)
        self.apply_filter(self.filter_edit.text())
        self._update_status(len(connected_layers))

    def _build_item(self, layer) -> QTreeWidgetItem:
        info = DataConnectorLogic.read_connection_info(layer)
        item = QTreeWidgetItem([
            layer.name(),
            DataConnectorLogic.geometry_type_label(layer),
            info.get('source_uri', ''),
            info.get('service', ''),
            info.get('source_crs', ''),
            info.get('target_crs', ''),
            info.get('last_updated', ''),
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, layer.id())
        item.setToolTip(2, info.get('source_uri', ''))
        return item

    def apply_filter(self, text):
        """Hide rows that do not match the filter text in any column."""
        needle = (text or '').strip().lower()
        visible = 0

        for index in range(self.layer_tree.topLevelItemCount()):
            item = self.layer_tree.topLevelItem(index)
            matches = not needle or any(
                needle in item.text(column).lower() for column in range(len(COLUMNS))
            )
            item.setHidden(not matches)
            if matches:
                visible += 1

        self._update_status(visible)

    def _update_status(self, count):
        if self.layer_tree.topLevelItemCount() == 0:
            self.status_label.setText("No connected layers in this project.")
        else:
            self.status_label.setText(f"{count} connected layer(s)")

    # ---------------------------------------------------------------- actions

    def open_add_connected_layer_dialog(self):
        """Show the Add New Connected Layer dialog and run the extraction."""
        dialog = AddConnectedLayerDialog(self.iface, self)
        if not dialog.exec():
            return

        self.run_extraction(dialog)
        self.refresh_layers()

    def open_add_raster_layer_dialog(self):
        """Show the Add New Raster Layers dialog and run the raster extraction."""
        dialog = AddRasterLayerDialog(self.iface, self)
        if not dialog.exec():
            return

        self.run_raster_extraction(dialog)
        self.refresh_layers()

    def run_raster_extraction(self, dialog):
        """Render the selected raster service to disk behind a progress bar."""
        try:
            extent_geometry, extent_crs, _ = DataConnectorExtractor.build_extent_geometry(
                dialog.get_extent_mode(),
                self.iface,
                extent_layer=dialog.get_extent_layer(),
                mask_layer=dialog.get_mask_layer(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Data Connector", str(exc))
            return

        progress = QProgressDialog("Extracting raster...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Data Connector")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def update_progress(message, percent):
            progress.setLabelText(message)
            progress.setValue(percent)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise Exception("Extraction cancelled by user")

        try:
            results = DataConnectorRasterExtractor.extract_layer(
                source_layer=dialog.get_selected_layer(),
                extent_geometry=extent_geometry,
                extent_crs=extent_crs,
                target_crs=dialog.get_target_crs(),
                zoom=dialog.get_zoom(),
                output_format=dialog.get_output_format(),
                output_path=dialog.get_output_path(),
                replace_source=dialog.get_replace_layer(),
                progress_callback=update_progress,
            )
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Data Connector", f"Extraction failed:\n{exc}")
            return
        finally:
            progress.close()

        self._report_results(results)

    def run_extraction(self, dialog):
        """Execute the extraction described by the dialog behind a progress bar."""
        try:
            extent_geometry, extent_crs, clip_to_geometry = (
                DataConnectorExtractor.build_extent_geometry(
                    dialog.get_extent_mode(),
                    self.iface,
                    extent_layer=dialog.get_extent_layer(),
                    mask_layer=dialog.get_mask_layer(),
                )
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Data Connector", str(exc))
            return

        progress = QProgressDialog("Extracting layers...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Data Connector")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def update_progress(message, percent):
            progress.setLabelText(message)
            progress.setValue(percent)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise Exception("Extraction cancelled by user")

        try:
            results = DataConnectorExtractor.extract_layers(
                source_layers=dialog.get_selected_layers(),
                extent_geometry=extent_geometry,
                extent_crs=extent_crs,
                target_crs=dialog.get_target_crs(),
                output_format=dialog.get_output_format(),
                output_mode=dialog.get_output_mode(),
                output_path=dialog.get_output_path(),
                clip_to_geometry=clip_to_geometry,
                replace_source=dialog.get_replace_layer(),
                progress_callback=update_progress,
            )
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Data Connector", f"Extraction failed:\n{exc}")
            return
        finally:
            progress.close()

        self._report_results(results)

    def _report_results(self, results, count_key='extracted', verb='Extracted'):
        """Summarise the outcome, listing any per-layer failures."""
        summary = [f"{verb} {results[count_key]} layer(s)."]

        if results['warnings']:
            summary.append("\nWarnings:")
            summary.extend(f"  • {warning}" for warning in results['warnings'])

        if results['errors']:
            summary.append("\nErrors:")
            summary.extend(f"  • {error}" for error in results['errors'])
            QMessageBox.warning(self, "Data Connector", "\n".join(summary))
        else:
            QMessageBox.information(self, "Data Connector", "\n".join(summary))

    def get_selected_layer_ids(self) -> list:
        ids = []
        for item in self.layer_tree.selectedItems():
            layer_id = item.data(0, Qt.ItemDataRole.UserRole)
            if layer_id:
                ids.append(layer_id)
        return ids

    def closeEvent(self, event):
        self.disconnect_project_signals()
        super().closeEvent(event)
