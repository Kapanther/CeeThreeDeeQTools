# -*- coding: utf-8 -*-
"""
Dialog for importing LandXML (Civil 3D) data into QGIS.

Workflow: browse to a LandXML file -> Read (structure only) -> tick the
entities to import -> choose source/target CRS -> Import.

Only Alignments (horizontal geometry) and their Profiles are implemented;
Points, Surfaces and Pipe Networks are listed but disabled (WIP).
"""

import os

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .ctdq_LandXMLImportLogic import LandXMLImportLogic
from .ctdq_LandXMLImportParser import LandXMLParser

SETTINGS_LAST_FOLDER = "CeeThreeDeeQTools/LandXMLImport/lastFolder"

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_DATA = Qt.ItemDataRole.UserRole + 1


class LandXMLImportDialog(QDialog):
    """Main UI for the LandXML import tool."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.structure = None
        self._auto_output_path = ""

        self.setWindowTitle("LandXML Import")
        self.setMinimumSize(1000, 680)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(self._build_file_group())

        columns = QHBoxLayout()
        columns.addWidget(self._build_tree_group(), 3)

        right_column = QVBoxLayout()
        right_column.addWidget(self._build_options_group())
        right_column.addWidget(self._build_crs_group())
        right_column.addWidget(self._build_output_group())
        right_column.addStretch()
        columns.addLayout(right_column, 2)
        layout.addLayout(columns, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(90)
        layout.addWidget(self.console)

        button_row = QHBoxLayout()
        self.import_button = QPushButton("Import Selected")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.on_import)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(self.import_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.setLayout(layout)

    def _build_file_group(self):
        group = QGroupBox("LandXML File")
        group_layout = QHBoxLayout()

        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Path to a .xml LandXML file")
        self.file_edit.editingFinished.connect(self.on_file_edited)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.on_browse)

        group_layout.addWidget(self.file_edit, 1)
        group_layout.addWidget(self.browse_button)
        group.setLayout(group_layout)
        return group

    def _build_tree_group(self):
        group = QGroupBox("Contents")
        group_layout = QVBoxLayout()

        self.info_label = QLabel("No file read yet.")
        group_layout.addWidget(self.info_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Details"])
        self.tree.setColumnWidth(0, 320)
        self.tree.itemChanged.connect(self.on_item_changed)
        group_layout.addWidget(self.tree, 1)

        select_row = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_button = QPushButton("Select None")
        self.select_none_button.clicked.connect(lambda: self._set_all_checked(False))
        select_row.addWidget(self.select_all_button)
        select_row.addWidget(self.select_none_button)
        select_row.addStretch()
        group_layout.addLayout(select_row)

        group.setLayout(group_layout)
        return group

    def _build_options_group(self):
        group = QGroupBox("Import Options")
        group_layout = QVBoxLayout()

        structure_box = QVBoxLayout()
        structure_box.addWidget(QLabel("Alignment Layer structure:"))
        self.structure_group = QButtonGroup(self)
        self.structure_alignment_radio = QRadioButton(
            "One layer per alignment (with its profiles)")
        self.structure_alignment_radio.setChecked(True)
        self.structure_all_radio = QRadioButton(
            "Combine all - one layer for the whole file")
        self.structure_separate_radio = QRadioButton("Separate layer per object")
        for radio in (self.structure_alignment_radio, self.structure_all_radio,
                      self.structure_separate_radio):
            self.structure_group.addButton(radio)
            radio.toggled.connect(self.on_structure_changed)
            structure_box.addWidget(radio)
        group_layout.addLayout(structure_box)

        tolerance_row = QHBoxLayout()
        tolerance_row.addWidget(QLabel("Horizontal curve tolerance (m):"))
        self.curve_tolerance_spin = QDoubleSpinBox()
        self.curve_tolerance_spin.setDecimals(3)
        self.curve_tolerance_spin.setRange(0.001, 5.0)
        self.curve_tolerance_spin.setSingleStep(0.01)
        self.curve_tolerance_spin.setValue(0.01)
        self.curve_tolerance_spin.setMinimumWidth(110)
        tolerance_row.addWidget(self.curve_tolerance_spin)
        tolerance_row.addStretch()
        group_layout.addLayout(tolerance_row)

        vertical_row = QHBoxLayout()
        self.densify_vcurves_check = QCheckBox("Densify vertical curves, tolerance (m):")
        self.densify_vcurves_check.setChecked(True)
        self.vertical_tolerance_spin = QDoubleSpinBox()
        self.vertical_tolerance_spin.setDecimals(4)
        self.vertical_tolerance_spin.setRange(0.0005, 1.0)
        self.vertical_tolerance_spin.setSingleStep(0.005)
        self.vertical_tolerance_spin.setValue(0.005)
        self.vertical_tolerance_spin.setMinimumWidth(110)
        self.densify_vcurves_check.toggled.connect(self.vertical_tolerance_spin.setEnabled)
        vertical_row.addWidget(self.densify_vcurves_check)
        vertical_row.addWidget(self.vertical_tolerance_spin)
        vertical_row.addStretch()
        group_layout.addLayout(vertical_row)

        self.group_layers_check = QCheckBox("Place imported layers in a group named after the file")
        self.group_layers_check.setChecked(True)
        group_layout.addWidget(self.group_layers_check)

        self.group_per_alignment_check = QCheckBox("Create a sub-group for each alignment")
        self.group_per_alignment_check.setChecked(True)
        self.group_per_alignment_check.setEnabled(False)
        group_layout.addWidget(self.group_per_alignment_check)

        self.hidden_faces_check = QCheckBox(
            "Surfaces: include hidden faces (ignore boundaries/voids)")
        group_layout.addWidget(self.hidden_faces_check)

        self.contours_check = QCheckBox("Surfaces: automatically generate contours")
        self.contours_check.setChecked(True)
        self.contours_check.toggled.connect(self.on_contours_toggled)
        group_layout.addWidget(self.contours_check)

        interval_row = QHBoxLayout()
        interval_row.addSpacing(20)
        interval_row.addWidget(QLabel("Minor (m):"))
        self.minor_interval_spin = QDoubleSpinBox()
        self.minor_interval_spin.setDecimals(3)
        self.minor_interval_spin.setRange(0.001, 1000.0)
        self.minor_interval_spin.setSingleStep(0.05)
        self.minor_interval_spin.setValue(1.0)
        self.minor_interval_spin.setMinimumWidth(110)
        interval_row.addWidget(self.minor_interval_spin)
        interval_row.addWidget(QLabel("Major (m):"))
        self.major_interval_spin = QDoubleSpinBox()
        self.major_interval_spin.setDecimals(3)
        self.major_interval_spin.setRange(0.001, 1000.0)
        self.major_interval_spin.setSingleStep(0.25)
        self.major_interval_spin.setValue(5.0)
        self.major_interval_spin.setMinimumWidth(110)
        interval_row.addWidget(self.major_interval_spin)
        interval_row.addStretch()
        group_layout.addLayout(interval_row)

        self.stationing_check = QCheckBox("Create stationing point layer (WIP)")
        self.stationing_check.setEnabled(False)
        group_layout.addWidget(self.stationing_check)
        group.setLayout(group_layout)
        return group

    def _build_output_group(self):
        group = QGroupBox("Output")
        group_layout = QVBoxLayout()

        self.output_mode_group = QButtonGroup(self)
        self.output_memory_radio = QRadioButton("Temporary (memory) layers")
        self.output_memory_radio.setChecked(True)
        self.output_gpkg_radio = QRadioButton("GeoPackage")
        self.output_shp_radio = QRadioButton("Folder of shapefiles")
        for radio in (self.output_memory_radio, self.output_gpkg_radio,
                      self.output_shp_radio):
            self.output_mode_group.addButton(radio)
            radio.toggled.connect(self.on_output_mode_changed)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.output_memory_radio)
        mode_row.addWidget(self.output_gpkg_radio)
        mode_row.addWidget(self.output_shp_radio)
        mode_row.addStretch()
        group_layout.addLayout(mode_row)

        path_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setEnabled(False)
        self.output_browse_button = QPushButton("Browse...")
        self.output_browse_button.setEnabled(False)
        self.output_browse_button.clicked.connect(self.on_browse_output)
        path_row.addWidget(self.output_path_edit, 1)
        path_row.addWidget(self.output_browse_button)
        group_layout.addLayout(path_row)

        group.setLayout(group_layout)
        return group

    def _build_crs_group(self):
        group = QGroupBox("Coordinate Reference Systems")
        group_layout = QVBoxLayout()

        project_crs = QgsProject.instance().crs()

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source CRS (LandXML):"))
        self.source_crs_selector = QgsProjectionSelectionWidget()
        self.source_crs_selector.setCrs(project_crs)
        source_row.addWidget(self.source_crs_selector, 1)
        group_layout.addLayout(source_row)

        self.crs_mode_group = QButtonGroup(self)
        self.crs_project_radio = QRadioButton(
            "Target: Use Project CRS ({0})".format(project_crs.authid() or "not set"))
        self.crs_project_radio.setChecked(True)
        self.crs_custom_radio = QRadioButton("Target: Use CRS")
        self.crs_mode_group.addButton(self.crs_project_radio)
        self.crs_mode_group.addButton(self.crs_custom_radio)
        self.crs_project_radio.toggled.connect(self.on_crs_mode_changed)
        group_layout.addWidget(self.crs_project_radio)

        target_row = QHBoxLayout()
        target_row.addWidget(self.crs_custom_radio)
        self.target_crs_selector = QgsProjectionSelectionWidget()
        self.target_crs_selector.setCrs(project_crs)
        self.target_crs_selector.setEnabled(False)
        target_row.addWidget(self.target_crs_selector, 1)
        group_layout.addLayout(target_row)

        group.setLayout(group_layout)
        return group

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_crs_mode_changed(self, _checked=False):
        self.target_crs_selector.setEnabled(self.crs_custom_radio.isChecked())

    def on_structure_changed(self, _checked=False):
        self.group_per_alignment_check.setEnabled(
            self.structure_separate_radio.isChecked())

    def on_contours_toggled(self, checked):
        self.minor_interval_spin.setEnabled(checked)
        self.major_interval_spin.setEnabled(checked)

    def get_structure(self):
        if self.structure_all_radio.isChecked():
            return 'all'
        if self.structure_separate_radio.isChecked():
            return 'separate'
        return 'alignment'

    def on_output_mode_changed(self, _checked=False):
        needs_path = not self.output_memory_radio.isChecked()
        self.output_path_edit.setEnabled(needs_path)
        self.output_browse_button.setEnabled(needs_path)
        if needs_path:
            self._suggest_output_path()

    def _suggest_output_path(self):
        """Fill in a default path unless the user typed their own."""
        current = self.output_path_edit.text().strip()
        if current and current != self._auto_output_path:
            return
        self._auto_output_path = self._default_output_path()
        self.output_path_edit.setText(self._auto_output_path)

    def on_browse_output(self):
        if self.output_gpkg_radio.isChecked():
            path, _ = QFileDialog.getSaveFileName(
                self, "Output GeoPackage", self.output_path_edit.text(),
                "GeoPackage (*.gpkg)")
            if path and not path.lower().endswith('.gpkg'):
                path += '.gpkg'
        else:
            path = QFileDialog.getExistingDirectory(
                self, "Output Folder for Shapefiles",
                self.output_path_edit.text())
        if path:
            self.output_path_edit.setText(path)

    def on_browse(self):
        settings = QgsSettings()
        start_dir = settings.value(SETTINGS_LAST_FOLDER, "")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select LandXML File", start_dir,
            "LandXML Files (*.xml *.landxml);;All Files (*)")
        if file_path:
            self.file_edit.setText(file_path)
            settings.setValue(SETTINGS_LAST_FOLDER, os.path.dirname(file_path))
            self.read_file(file_path)

    def on_file_edited(self):
        """Re-read when the path is typed in and differs from what is loaded."""
        file_path = self.file_edit.text().strip()
        if not file_path or not os.path.isfile(file_path):
            return
        if self.structure is not None and self.structure.file_path == file_path:
            return
        self.read_file(file_path)

    def read_file(self, file_path):
        self.console.clear()
        self.progress_bar.setValue(0)
        try:
            self.structure = LandXMLParser.scan_structure(
                file_path, lambda message, _percent: self.append_console(message))
        except Exception as exc:  # parsing errors are reported to the user
            self.structure = None
            self.tree.clear()
            self.import_button.setEnabled(False)
            self.append_console("Failed to read file: {0}".format(exc))
            QMessageBox.critical(self, "LandXML Import",
                                 "Could not read the LandXML file:\n{0}".format(exc))
            return

        self._populate_tree(self.structure)
        self.info_label.setText(
            "{0}  |  units: {1}  |  source: {2}".format(
                os.path.basename(file_path),
                self.structure.units or "unknown",
                self.structure.application or "unknown"))
        self.import_button.setEnabled(bool(
            self.structure.alignments or self.structure.surfaces
            or self.structure.point_groups))
        if not self.output_memory_radio.isChecked():
            self._suggest_output_path()

    def on_item_changed(self, item, column):
        if column != 0:
            return
        self.tree.blockSignals(True)
        self._apply_check_state(item, item.checkState(0))
        self.tree.blockSignals(False)

    def _apply_check_state(self, item, state):
        """Push a check state down through every checkable descendant."""
        for i in range(item.childCount()):
            child = item.child(i)
            if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                child.setCheckState(0, state)
            self._apply_check_state(child, state)

    def on_import(self):
        if self.structure is None:
            return

        (alignment_names, profile_keys, surface_names,
         point_group_keys) = self._collect_selection()
        if not (alignment_names or profile_keys or surface_names
                or point_group_keys):
            QMessageBox.information(
                self, "LandXML Import",
                "Tick at least one alignment, profile, surface or point group.")
            return

        source_crs = self.source_crs_selector.crs()
        target_crs = self.get_target_crs()
        if not source_crs.isValid():
            QMessageBox.warning(self, "LandXML Import",
                                "Please choose a valid source CRS.")
            return
        if not target_crs.isValid():
            QMessageBox.warning(self, "LandXML Import",
                                "Please choose a valid target CRS.")
            return

        group_name = None
        if self.group_layers_check.isChecked():
            group_name = os.path.splitext(
                os.path.basename(self.structure.file_path))[0]

        output_mode, output_path = self.get_output_settings()
        if output_mode == 'gpkg' and not output_path:
            QMessageBox.warning(self, "LandXML Import",
                                "Please choose an output GeoPackage.")
            return
        if output_mode == 'shp' and not os.path.isdir(output_path or ''):
            QMessageBox.warning(self, "LandXML Import",
                                "Please choose an existing output folder.")
            return

        self.progress_bar.setValue(0)
        # A very large tolerance effectively disables vertical densifying
        vertical_tolerance = (self.vertical_tolerance_spin.value()
                              if self.densify_vcurves_check.isChecked() else 1e9)
        try:
            results = LandXMLImportLogic.import_alignments(
                self.structure.file_path,
                alignment_names,
                profile_keys,
                source_crs,
                target_crs,
                curve_tolerance=self.curve_tolerance_spin.value(),
                vertical_tolerance=vertical_tolerance,
                structure=self.get_structure(),
                surface_names=surface_names,
                include_hidden_faces=self.hidden_faces_check.isChecked(),
                point_group_keys=point_group_keys,
                generate_contours=self.contours_check.isChecked(),
                minor_interval=self.minor_interval_spin.value(),
                major_interval=self.major_interval_spin.value(),
                group_name=group_name,
                group_per_alignment=self.group_per_alignment_check.isChecked(),
                output_mode=output_mode,
                output_path=output_path,
                progress_callback=self._progress,
            )
        except Exception as exc:  # keep the dialog alive on failure
            self.append_console("Import failed: {0}".format(exc))
            QMessageBox.critical(self, "LandXML Import",
                                 "Import failed:\n{0}".format(exc))
            return

        for warning in results['warnings']:
            self.append_console("Warning: {0}".format(warning))
        for error in results['errors']:
            self.append_console("Error: {0}".format(error))
        self.append_console(
            "Created {0} layer(s): {1}".format(
                len(results['layers']), ", ".join(results['layers']) or "none"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_target_crs(self) -> QgsCoordinateReferenceSystem:
        if self.crs_custom_radio.isChecked():
            return self.target_crs_selector.crs()
        return QgsProject.instance().crs()

    def get_output_settings(self):
        """Return ``(mode, path)`` where mode is memory / gpkg / shp."""
        if self.output_gpkg_radio.isChecked():
            return 'gpkg', self.output_path_edit.text().strip()
        if self.output_shp_radio.isChecked():
            return 'shp', self.output_path_edit.text().strip()
        return 'memory', None

    def _default_output_path(self):
        """Alongside the LandXML file, or the project folder as a fallback."""
        source = self.file_edit.text().strip()
        if source and os.path.isfile(source):
            folder = os.path.dirname(source)
            stem = os.path.splitext(os.path.basename(source))[0]
        else:
            project_path = QgsProject.instance().fileName()
            if not project_path:
                return ""
            folder = os.path.dirname(project_path)
            stem = os.path.splitext(os.path.basename(project_path))[0]
        if self.output_gpkg_radio.isChecked():
            return os.path.join(folder, stem + ".gpkg")
        return folder

    def append_console(self, message):
        self.console.append(message)

    def _progress(self, message, percent):
        if message:
            self.append_console(message)
        if percent is not None:
            self.progress_bar.setValue(int(percent))

    def _populate_tree(self, structure):
        self.tree.blockSignals(True)
        self.tree.clear()

        alignments_root = self._add_category("Alignments", len(structure.alignments))
        for alignment in structure.alignments:
            item = QTreeWidgetItem(alignments_root)
            item.setText(0, alignment['name'])
            item.setText(1, "length {0}".format(alignment['length'] or "n/a"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, ROLE_KIND, 'alignment')
            item.setData(0, ROLE_DATA, alignment['name'])
            for profile in alignment['profiles']:
                is_surface = profile.get('kind') == 'surf'
                child = QTreeWidgetItem(item)
                child.setText(0, profile['name'])
                child.setText(1, "surface profile" if is_surface else "design profile")
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setData(0, ROLE_KIND, 'profile')
                child.setData(0, ROLE_DATA,
                              (alignment['name'], profile.get('kind', 'align'),
                               profile['name']))
            alignments_root.setExpanded(True)
        alignments_root.setExpanded(True)

        points_root = self._add_category("Points", len(structure.point_groups))
        for point_group in structure.point_groups:
            child = QTreeWidgetItem(points_root)
            child.setText(0, point_group['name'])
            child.setText(1, "{0} point(s)".format(point_group['count']))
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
            child.setData(0, ROLE_KIND, 'pointgroup')
            child.setData(0, ROLE_DATA, point_group['key'])
        points_root.setExpanded(True)

        surfaces_root = self._add_category("Surfaces", len(structure.surfaces))
        for surface in structure.surfaces:
            child = QTreeWidgetItem(surfaces_root)
            child.setText(0, surface['name'])
            child.setText(1, "TIN surface (mesh)")
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
            child.setData(0, ROLE_KIND, 'surface')
            child.setData(0, ROLE_DATA, surface['name'])
        surfaces_root.setExpanded(True)

        networks_root = self._add_category("Pipe Networks", len(structure.pipe_networks),
                                           wip=True)
        for network in structure.pipe_networks:
            self._add_disabled_child(networks_root, network['name'], "pipe network")

        self.tree.blockSignals(False)

    def _add_category(self, label, count, wip=False):
        item = QTreeWidgetItem(self.tree)
        item.setText(0, "{0}{1}".format(label, " (not implemented yet)" if wip else ""))
        item.setText(1, "{0} item(s)".format(count))
        item.setData(0, ROLE_KIND, 'category')
        if wip:
            item.setDisabled(True)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
        return item

    def _add_disabled_child(self, parent, label, details):
        child = QTreeWidgetItem(parent)
        child.setText(0, label)
        child.setText(1, details)
        child.setDisabled(True)
        return child

    def _set_all_checked(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.isDisabled():
                continue
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, state)
            self._apply_check_state(item, state)
        self.tree.blockSignals(False)

    def _collect_selection(self):
        alignment_names = []
        profile_keys = []
        surface_names = []
        point_group_keys = []
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            for j in range(root.childCount()):
                item = root.child(j)
                kind = item.data(0, ROLE_KIND)
                checked = item.checkState(0) == Qt.CheckState.Checked
                if kind == 'surface':
                    if checked:
                        surface_names.append(item.data(0, ROLE_DATA))
                    continue
                if kind == 'pointgroup':
                    if checked:
                        point_group_keys.append(item.data(0, ROLE_DATA))
                    continue
                if kind != 'alignment':
                    continue
                if checked:
                    alignment_names.append(item.data(0, ROLE_DATA))
                for k in range(item.childCount()):
                    profile = item.child(k)
                    if profile.checkState(0) == Qt.CheckState.Checked:
                        profile_keys.append(profile.data(0, ROLE_DATA))
        return alignment_names, profile_keys, surface_names, point_group_keys
