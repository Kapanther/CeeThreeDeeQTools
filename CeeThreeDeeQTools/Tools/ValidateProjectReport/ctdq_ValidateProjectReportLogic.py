from urllib.parse import unquote


class ValidateProjectReportLogic:
    """Shared source normalization and project-layer comparison logic."""

    @staticmethod
    def normalize_path(path, case_sensitive):
        if not path:
            return ""

        if path.lower().startswith("file:"):
            normalized = path[5:]
            while normalized.startswith("/"):
                normalized = normalized[1:]
            normalized = unquote(normalized)
            if "?" in normalized:
                normalized = normalized.split("?", 1)[0]
        else:
            normalized = path.strip().replace("\\", "/")

        if "|" in normalized:
            normalized = normalized.split("|", 1)[0]
        if not case_sensitive:
            normalized = normalized.lower()
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        return normalized

    @classmethod
    def build_possible_layers(
        cls,
        source_rows,
        use_filter1,
        selected_categories1,
        use_filter2,
        selected_categories2,
        case_sensitive,
    ):
        possible_layers = {}
        for layer_name, source_path, category1, category2 in source_rows:
            if use_filter1 and (
                not category1 or str(category1) not in selected_categories1
            ):
                continue
            if use_filter2 and (
                not category2 or str(category2) not in selected_categories2
            ):
                continue

            if layer_name and source_path:
                normalized_layer_name = cls.normalize_path(layer_name, case_sensitive)
                normalized_source_path = cls.normalize_path(source_path, case_sensitive)
                possible_layers[normalized_layer_name] = {
                    "original_layer_name": layer_name,
                    "source_path": normalized_source_path,
                    "category1": category1,
                    "category2": category2,
                }
        return possible_layers

    @classmethod
    def validate_project_layers(
        cls,
        project_layers,
        possible_layers,
        layer_name_delimiter,
        case_sensitive,
        progress_callback=None,
    ):
        html_rows = []
        unmatched_layers = possible_layers.copy()
        matched_count = 0
        wrong_source_count = 0
        layer_name_not_found_count = 0
        total_count = 0

        for layer in project_layers.values():
            layer_name = layer.name()
            layer_source = layer.dataProvider().dataSourceUri()
            normalized_layer_name = cls.normalize_path(layer_name, case_sensitive)
            if layer_name_delimiter in normalized_layer_name:
                normalized_layer_name = normalized_layer_name.split(
                    layer_name_delimiter, 1
                )[0]
                if progress_callback:
                    progress_callback(
                        f"Layer name '{layer_name}' normalized to "
                        f"'{normalized_layer_name}' using delimiter "
                        f"'{layer_name_delimiter}'"
                    )
            normalized_layer_source = cls.normalize_path(layer_source, case_sensitive)

            if normalized_layer_name in possible_layers:
                reference_source = possible_layers[normalized_layer_name]["source_path"]
                category1 = possible_layers[normalized_layer_name]["category1"]
                category2 = possible_layers[normalized_layer_name]["category2"]
                if normalized_layer_source == reference_source:
                    check_result = "MATCHED"
                    matched_count += 1
                else:
                    check_result = "WRONGSOURCE"
                    wrong_source_count += 1
                unmatched_layers.pop(normalized_layer_name, None)
            else:
                reference_source = ""
                category1 = ""
                category2 = ""
                check_result = "LAYERNAMENOTFOUND"
                layer_name_not_found_count += 1

            if not layer_name or not check_result or not normalized_layer_source:
                if progress_callback:
                    progress_callback(f"Skipping blank line for layer '{layer_name}'")
                continue

            total_count += 1
            html_rows.append(
                (
                    layer_name,
                    check_result,
                    normalized_layer_source,
                    reference_source,
                    category1,
                    category2,
                )
            )
            if progress_callback:
                progress_callback(f"Layer '{layer_name}' checked: {check_result}")

        return (
            html_rows,
            unmatched_layers,
            matched_count,
            wrong_source_count,
            layer_name_not_found_count,
            total_count,
        )
