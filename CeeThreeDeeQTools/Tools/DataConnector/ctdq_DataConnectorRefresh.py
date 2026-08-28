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

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsFeature,
    QgsGeometry,
    QgsRectangle,
    QgsVectorDataProvider,
)

from .ctdq_DataConnectorLogic import DataConnectorLogic


class DataConnectorRefresh:
    """Re-extracts connected layers from their stored source, in place."""

    @staticmethod
    def refresh_layers(
        layers: list,
        override_extent_geometry: QgsGeometry = None,
        override_extent_crs: QgsCoordinateReferenceSystem = None,
        clip_to_geometry: bool = False,
        progress_callback=None,
    ) -> dict:
        """
        Reload each connected layer from its originating service.

        When no override extent is supplied the extent stored on each layer is reused.

        Returns:
            dict with 'refreshed', 'errors' and 'warnings'
        """
        results = {'refreshed': 0, 'errors': [], 'warnings': []}

        if not layers:
            results['errors'].append("No connected layers to refresh.")
            return results

        transform_context = QgsProject.instance().transformContext()
        total = len(layers)

        for index, layer in enumerate(layers):
            percent = int((index / total) * 100)
            DataConnectorRefresh._report(
                progress_callback, f"Refreshing '{layer.name()}'...", percent
            )

            try:
                DataConnectorRefresh._refresh_one(
                    layer,
                    override_extent_geometry,
                    override_extent_crs,
                    clip_to_geometry,
                    transform_context,
                    progress_callback,
                    percent,
                    results,
                )
            except Exception as exc:
                results['errors'].append(f"'{layer.name()}': {exc}")

        DataConnectorRefresh._report(progress_callback, "Refresh complete", 100)
        return results

    # ------------------------------------------------------------- internals

    @staticmethod
    def _report(progress_callback, message, percent):
        if progress_callback:
            progress_callback(message, percent)

    @staticmethod
    def _refresh_one(
        layer, override_geometry, override_crs, clip_to_geometry,
        transform_context, progress_callback, percent, results
    ):
        info = DataConnectorLogic.read_connection_info(layer)
        if not info:
            results['warnings'].append(f"'{layer.name()}': no connection metadata - skipped.")
            return

        if layer.isEditable():
            results['warnings'].append(
                f"'{layer.name()}': layer is in edit mode - skipped."
            )
            return

        source_layer = DataConnectorRefresh._open_source(info, layer.name())

        extent_geometry, extent_crs = DataConnectorRefresh._resolve_extent(
            info, override_geometry, override_crs
        )

        features = DataConnectorRefresh._read_features(
            source_layer, layer, extent_geometry, extent_crs,
            clip_to_geometry, transform_context, progress_callback, percent
        )

        if not features:
            results['warnings'].append(
                f"'{layer.name()}': no features returned for the extent - existing data kept."
            )
            return

        DataConnectorRefresh._replace_data(layer, features, results)

        stored_extent, stored_extent_crs = DataConnectorRefresh._extent_for_metadata(
            info, extent_geometry, extent_crs, override_geometry is not None
        )
        DataConnectorLogic.write_connection_info(
            layer,
            source_uri=info.get('source_uri', ''),
            service=info.get('service', ''),
            provider_key=info.get('provider_key', ''),
            source_crs=info.get('source_crs', ''),
            target_crs=layer.crs().authid(),
            extent=stored_extent,
            extent_crs=stored_extent_crs,
        )

        layer.updateExtents()
        layer.triggerRepaint()
        results['refreshed'] += 1

    @staticmethod
    def _open_source(info, display_name):
        """Rebuild the streamed layer from the stored URI and provider."""
        uri = info.get('source_uri', '')
        provider = info.get('provider_key', '')
        if not uri or not provider:
            raise ValueError("stored connection is incomplete.")

        source_layer = QgsVectorLayer(uri, f"{display_name} (source)", provider)
        if not source_layer.isValid():
            raise ValueError("could not connect to the original data source.")
        return source_layer

    @staticmethod
    def _resolve_extent(info, override_geometry, override_crs):
        """Use the override extent when given, otherwise the extent stored on the layer."""
        if override_geometry is not None:
            return override_geometry, override_crs

        raw_extent = info.get('extent', '')
        parts = [part for part in raw_extent.split(',') if part.strip()]
        if len(parts) != 4:
            raise ValueError("stored extent is missing or invalid.")

        try:
            xmin, ymin, xmax, ymax = (float(part) for part in parts)
        except ValueError:
            raise ValueError("stored extent could not be read.")

        crs = QgsCoordinateReferenceSystem(info.get('extent_crs', ''))
        if not crs.isValid():
            crs = QgsProject.instance().crs()

        return QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax)), crs

    @staticmethod
    def _extent_for_metadata(info, extent_geometry, extent_crs, extent_changed):
        if not extent_changed:
            return info.get('extent', ''), info.get('extent_crs', '')

        rect = extent_geometry.boundingBox()
        return (
            f"{rect.xMinimum()},{rect.yMinimum()},{rect.xMaximum()},{rect.yMaximum()}",
            extent_crs.authid() if extent_crs else '',
        )

    @staticmethod
    def _read_features(
        source_layer, target_layer, extent_geometry, extent_crs,
        clip_to_geometry, transform_context, progress_callback, percent
    ):
        """Pull features from the service, clipped and reprojected to the target layer."""
        source_crs = source_layer.crs()
        target_crs = target_layer.crs()

        request_geometry = QgsGeometry(extent_geometry)
        if extent_crs.isValid() and source_crs.isValid() and extent_crs != source_crs:
            request_geometry.transform(
                QgsCoordinateTransform(extent_crs, source_crs, transform_context)
            )

        clip_geometry = QgsGeometry(extent_geometry)
        if extent_crs.isValid() and target_crs.isValid() and extent_crs != target_crs:
            clip_geometry.transform(
                QgsCoordinateTransform(extent_crs, target_crs, transform_context)
            )

        to_target = None
        if source_crs.isValid() and target_crs.isValid() and source_crs != target_crs:
            to_target = QgsCoordinateTransform(source_crs, target_crs, transform_context)

        field_map = DataConnectorRefresh._build_field_map(source_layer, target_layer)
        target_fields = target_layer.fields()

        request = QgsFeatureRequest().setFilterRect(request_geometry.boundingBox())
        features = []
        count = 0

        for source_feature in source_layer.getFeatures(request):
            count += 1
            if count % 500 == 0:
                DataConnectorRefresh._report(
                    progress_callback,
                    f"Reading '{target_layer.name()}' - {count} features...",
                    percent,
                )

            new_feature = QgsFeature(target_fields)
            for target_index, source_index in field_map.items():
                new_feature.setAttribute(target_index, source_feature.attribute(source_index))

            geometry = source_feature.geometry()
            if geometry and not geometry.isEmpty():
                if to_target:
                    geometry = QgsGeometry(geometry)
                    geometry.transform(to_target)
                if clip_to_geometry:
                    geometry = geometry.intersection(clip_geometry)
                    if geometry.isEmpty():
                        continue
                new_feature.setGeometry(geometry)

            features.append(new_feature)

        return features

    @staticmethod
    def _build_field_map(source_layer, target_layer) -> dict:
        """Match target fields to source fields by name, tolerating schema drift."""
        source_fields = source_layer.fields()
        field_map = {}
        for target_index, field in enumerate(target_layer.fields()):
            source_index = source_fields.lookupField(field.name())
            if source_index >= 0:
                field_map[target_index] = source_index
        return field_map

    @staticmethod
    def _replace_data(layer, features, results):
        """Swap the layer's contents for the freshly downloaded features."""
        provider = layer.dataProvider()
        capabilities = provider.capabilities()

        if not (capabilities & QgsVectorDataProvider.Capability.AddFeatures):
            raise ValueError("output does not support adding features.")

        if not DataConnectorRefresh._clear_existing(layer, provider, capabilities):
            raise ValueError("existing data could not be cleared.")

        added = provider.addFeatures(features)
        if not added:
            raise ValueError(f"could not write features - {provider.lastError()}")

        if provider.featureCount() != len(features):
            results['warnings'].append(
                f"'{layer.name()}': wrote {provider.featureCount()} of {len(features)} features."
            )

    @staticmethod
    def _clear_existing(layer, provider, capabilities) -> bool:
        if capabilities & QgsVectorDataProvider.Capability.FastTruncate:
            if provider.truncate():
                return True

        if not (capabilities & QgsVectorDataProvider.Capability.DeleteFeatures):
            return False

        feature_ids = [feature.id() for feature in layer.getFeatures(
            QgsFeatureRequest().setNoAttributes()
        )]
        if not feature_ids:
            return True
        return provider.deleteFeatures(feature_ids)
