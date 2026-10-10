from html import escape
import os


class ValidateProjectReportReportWriter:
    """Writes the HTML validation report and an optional CSV companion."""

    @staticmethod
    def write_reports(
        report_path,
        details,
        html_rows,
        unmatched_layers,
        matched_count,
        wrong_source_count,
        layer_name_not_found_count,
        total_count,
        generate_csv,
    ):
        html_report_path = report_path
        csv_report_path = os.path.splitext(html_report_path)[0] + ".csv"
        ValidateProjectReportReportWriter._write_html_report(
            html_report_path,
            details,
            html_rows,
            unmatched_layers,
            matched_count,
            wrong_source_count,
            layer_name_not_found_count,
            total_count,
        )
        if generate_csv:
            ValidateProjectReportReportWriter._write_csv_report(
                csv_report_path,
                details,
                html_rows,
                unmatched_layers,
                matched_count,
                wrong_source_count,
                layer_name_not_found_count,
                total_count,
            )
        return html_report_path, csv_report_path if generate_csv else None

    @staticmethod
    def _write_csv_report(
        report_path,
        details,
        html_rows,
        unmatched_layers,
        matched_count,
        wrong_source_count,
        layer_name_not_found_count,
        total_count,
    ):
        detail_lines = [
            ("ReportDate", details["report_date"]),
            ("ReportUser", details["report_user"]),
            ("QGISprojectPath", details["qgis_project_path"]),
            ("ValidationSourceType", details["source_mode"]),
            ("ValidationExcelFilePath", details["excel_file"]),
            ("ValidationExcelSheet", details["sheet_name"]),
            ("ValidationExcelDateModified", details["excel_date_modified"]),
            ("ValidationProjectLayerName", details["project_layer_name"]),
            ("ValidationProjectLayerSource", details["project_layer_source"]),
            ("ValidationJSONUrl", details["json_url"]),
            ("ValidationJSONAuthConfigId", details["json_auth_config_id"]),
            ("ValidationLayerNameField", details["layer_name_field"]),
            ("ValidationSourceField", details["source_path_field"]),
            ("ValidationFilterCatergories1", details["filter_categories1"]),
            ("ValidationFilterCatergories2", details["filter_categories2"]),
        ]
        with open(report_path, "w", encoding="utf-8") as report_file:
            report_file.write("#VALIDATIONDETAILS#\n")
            report_file.writelines(f"{key}={value}\n" for key, value in detail_lines)
            report_file.write("\n#DATASOURCECHECK#\n")
            report_file.write(
                "LayerName,CheckResult,LayerSource,ReferenceSource,"
                "FilterCategory,SecondFilterCategory\n"
            )
            for row in html_rows:
                report_file.write(",".join(map(str, row)) + "\n")

            report_file.write(
                "\n#MISSINGVALIDATION#\n"
                "LayerName,SourcePath,FilterCategory,SecondFilterCategory\n"
            )
            for layer_data in unmatched_layers.values():
                report_file.write(
                    f"{layer_data['original_layer_name']},{layer_data['source_path']},"
                    f"{layer_data['category1']},{layer_data['category2']}\n"
                )

            report_file.write("\n#VALIDATIONSUMMARY#\n")
            report_file.write(f"DATASOURCES_MATCHED={matched_count}\n")
            report_file.write(f"DATASOURCES_WRONGSOURCE={wrong_source_count}\n")
            report_file.write(
                f"DATASOURCES_LAYERNAMENOTFOUND={layer_name_not_found_count}\n"
            )
            report_file.write(f"DATASOURCES_TOTAL={total_count}\n")

    @staticmethod
    def _write_html_report(
        report_path,
        details,
        html_rows,
        unmatched_layers,
        matched_count,
        wrong_source_count,
        layer_name_not_found_count,
        total_count,
    ):
        with open(report_path, "w", encoding="utf-8") as html_file:
            html_file.write(
                "<html><head><title>Validation Report</title><style>"
                "table { border-collapse: collapse; width: 100%; }"
                "th, td { border: 1px solid black; padding: 8px; text-align: left; }"
                "th { background-color: #f2f2f2; cursor: pointer; }"
                ".matched { background-color: #d4edda; }"
                ".layernotfound { background-color: #fff3cd; }"
                ".wrongsource { background-color: #f8d7da; }"
                "</style><script>"
                "function sortTable(tableId, columnIndex) {"
                "const table = document.getElementById(tableId);"
                "const rows = Array.from(table.rows).slice(1);"
                "const isAscending = table.getAttribute('data-sort-order') !== 'asc';"
                "rows.sort((rowA, rowB) => {"
                "const cellA = rowA.cells[columnIndex].innerText.toLowerCase();"
                "const cellB = rowB.cells[columnIndex].innerText.toLowerCase();"
                "if (cellA < cellB) return isAscending ? -1 : 1;"
                "if (cellA > cellB) return isAscending ? 1 : -1;"
                "return 0; });"
                "rows.forEach(row => table.tBodies[0].appendChild(row));"
                "table.setAttribute('data-sort-order', isAscending ? 'asc' : 'desc');"
                "}</script></head><body><h1>Validation Report</h1>"
                "<h2>Validation Details</h2>"
            )
            details_html = [
                ("Report Date", details["report_date"]),
                ("Report User", details["report_user"]),
                ("QGIS Project Path", details["qgis_project_path"]),
                ("Validation Source Type", details["source_mode"]),
            ]
            if details["source_mode"] == "Excel Workbook":
                details_html.extend(
                    [
                        ("Validation Excel File Path", details["excel_file"]),
                        ("Validation Excel Sheet", details["sheet_name"]),
                        (
                            "Validation Excel Date Modified",
                            details["excel_date_modified"],
                        ),
                    ]
                )
            elif details["source_mode"] == "Project Layer":
                details_html.extend(
                    [
                        ("Validation Project Layer", details["project_layer_name"]),
                        (
                            "Validation Project Layer Source",
                            details["project_layer_source"],
                        ),
                    ]
                )
            else:
                details_html.append(
                    ("Validation JSON URL", details["json_url"])
                )
            details_html.extend(
                [
                    ("Validation Layer Name Field", details["layer_name_field"]),
                    ("Validation Source Field", details["source_path_field"]),
                    ("Validation Filter Categories 1", details["filter_categories1"]),
                    ("Validation Filter Categories 2", details["filter_categories2"]),
                ]
            )
            for label, value in details_html:
                html_file.write(
                    f"<p><b>{escape(str(label))}:</b> {escape(str(value))}</p>"
                )

            html_file.write(
                "<h2>Data Source Check</h2><table id='datasource-check'><thead><tr>"
            )
            for index, heading in enumerate(
                (
                    "Layer Name",
                    "Check Result",
                    "Layer Source",
                    "Reference Source",
                    "Filter Category",
                    "Second Filter Category",
                )
            ):
                html_file.write(
                    f"<th onclick=\"sortTable('datasource-check', {index})\">"
                    f"{heading}</th>"
                )
            html_file.write("</tr></thead><tbody>")
            for row in html_rows:
                result_class = {
                    "MATCHED": "matched",
                    "LAYERNAMENOTFOUND": "layernotfound",
                    "WRONGSOURCE": "wrongsource",
                }.get(row[1], "")
                html_file.write(
                    f"<tr><td>{escape(str(row[0]))}</td>"
                    f"<td class='{result_class}'>{escape(str(row[1]))}</td>"
                    + "".join(f"<td>{escape(str(value))}</td>" for value in row[2:])
                    + "</tr>"
                )
            html_file.write("</tbody></table><h2>Missing Validation Layers</h2>")
            html_file.write(
                "<table id='missing-validation'><thead><tr>"
            )
            for index, heading in enumerate(
                ("Layer Name", "Source Path", "Filter Category", "Second Filter Category")
            ):
                html_file.write(
                    f"<th onclick=\"sortTable('missing-validation', {index})\">"
                    f"{heading}</th>"
                )
            html_file.write("</tr></thead><tbody>")
            for layer_data in unmatched_layers.values():
                values = (
                    layer_data["original_layer_name"],
                    layer_data["source_path"],
                    layer_data["category1"],
                    layer_data["category2"],
                )
                html_file.write(
                    "<tr>"
                    + "".join(f"<td>{escape(str(value))}</td>" for value in values)
                    + "</tr>"
                )
            html_file.write("</tbody></table><h2>Validation Summary</h2>")
            html_file.write(
                "<p><b>Matched:</b> <span style='color: #155724; "
                f"background-color: #d4edda;'>Matched</span> ({matched_count})</p>"
                "<p><b>Wrong Source:</b> <span style='color: #721c24; "
                f"background-color: #f8d7da;'>Wrong Source</span> ({wrong_source_count})</p>"
                "<p><b>Layer Name Not Found:</b> <span style='color: #856404; "
                f"background-color: #fff3cd;'>Layer Name Not Found</span> "
                f"({layer_name_not_found_count})</p>"
                f"<p><b>Total:</b> {total_count}</p></body></html>"
            )
