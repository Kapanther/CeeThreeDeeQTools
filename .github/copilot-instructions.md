# CeeThreeDee QTools - AI Agent Instructions

## Project Overview
QGIS plugin suite for civil/geo engineers providing processing algorithms, custom tools, and UI components. The plugin integrates with QGIS's Processing framework and adds custom dialogs/dock widgets accessible from the Plugins menu.

## Architecture

### Two-Tier Tool System
1. **Processing Algorithms** (`CeeThreeDeeQTools/Processing/`): QGIS Processing framework tools (appear in Processing Toolbox)
   - Inherit from `QgsProcessingAlgorithm` or `ctdqAlgoBase`
   - Registered via `CTDQProvider` in `ctdq_provider.py`
   - Each algorithm defines `initAlgorithm()` for parameters and `processAlgorithm()` for execution
   - Must be manually added to `loadAlgorithms()` in provider

2. **Custom Tools** (`CeeThreeDeeQTools/Tools/`): Dialog-based UI tools (appear in Plugins > CeeThreeDee Qtools menu)
   - Separated into Dialog (UI) and Logic (business) classes
   - **Dialog-Logic Pattern**: Dialog classes handle UI/user input, Logic classes contain stateless business operations
   - Registered in `ctdq_plugin.py`'s `initGui()` method with menu actions

### Dialog-Logic Separation Pattern
All custom tools follow this pattern:
- `*Dialog.py`: UI setup, user interaction, progress display, callback registration
- `*Logic.py`: Pure business logic as static methods, no UI dependencies
- Plugin calls Dialog, Dialog registers callback, callback invokes Logic with collected parameters
- Example: `MirrorProjectDialog` ↔ `MirrorProjectLogic.export_layers_to_projects()`

### Key Plugin Files
- `__init__.py`: Entry point returning `CTDQPlugin` instance
- `ctdq_plugin.py`: Main plugin class managing menu, tool registration, and lifecycle
- `ctdq_provider.py`: Processing provider registering algorithms
- `ctdq_support.py`: Shared utilities, settings, help text, and constants

## Development Workflows

### Adding a New Processing Algorithm
1. Create file in `CeeThreeDeeQTools/Processing/` inheriting from `ctdqAlgoBase`
2. Implement `initAlgorithm()`, `processAlgorithm()`, `name()`, `displayName()`, `group()`, `groupId()`
3. Import and instantiate in `ctdq_provider.py`'s `loadAlgorithms()`
4. Add metadata to `ctdprocessing_command_info` in `ctdq_support.py` for help text

### Adding a New Custom Tool
1. Create subdirectory in `CeeThreeDeeQTools/Tools/` with `*Dialog.py` and `*Logic.py`
2. Dialog: Inherit from `QDialog` or `QDockWidget`, implement UI and callback registration
3. Logic: Static methods only, accept progress callback as parameter
4. Register in `ctdq_plugin.py`: Add action in `initGui()`, add open method (e.g., `openMirrorProjectDialog()`)
5. Handle cleanup in `unload()` if needed

### Building & Deploying
- **Quick Deploy (Windows)**: Run `Debug.bat` - uses `robocopy` to sync to `%appdata%\QGIS\QGIS3\profiles\default\python\plugins\CeeThreeDeeQTools`
- **Compile Resources**: `compile.bat` runs `pyrcc5` in QGIS OSGeo4W environment (use when `.qrc` changes)
- **Install QGIS**: `qgis_deploy_install_upgrade_ltr.ps1` - PowerShell script to install/upgrade QGIS LTR
- **Makefile**: Legacy GNU Make targets (deploy, package, upload) - less commonly used on Windows

### Testing & Debugging
- No automated test suite currently
- Manual testing: Deploy with `Debug.bat`, use Plugin Reloader plugin in QGIS to refresh the plugin (faster than restarting QGIS)
- Plugin Reloader: Install from QGIS Plugin Manager - allows hot-reloading of plugins during development without closing QGIS
- Alternative: Restart QGIS after deployment for full clean reload
- Check Processing settings: Processing Toolbox → Settings (Cog) → Providers → CeeThreeDee Qtools

## Code Conventions

### File Size Limits
**Keep files under 1000 lines** - AI agents struggle with larger files. When a module approaches this limit:
- Split by responsibility (e.g., `layer_service.py` → `layer_query_service.py` + `layer_modification_service.py`)
- Extract domain-specific logic into separate files
- Create focused widget/service modules rather than monolithic classes
- Example: LayersAdvanced tool uses services/ and ui/ subdirectories with focused <350 line modules

### Processing Settings
- Global settings defined in `ctdprocessing_settingsdefaults` (precision values for elevation/area/volume)
- Access via `CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_elevation", fallback_value=2)`
- Settings registered in provider's `load()` method using `ProcessingConfig.addSetting()`

### Group Organization
Processing algorithms organized into groups (defined in `ctdgroup_info`):
- Group 1: "Projects" - project management tools
- Group 2: "Hydrology" - catchment/stream analysis
- Group 3: "3D" - elevation/terrain tools

### Progress Reporting Pattern
Long-running operations accept `progress_callback(message: str, percent: int)`:
```python
def some_operation(layers, target_path, progress_callback=None):
    if progress_callback:
        progress_callback("Processing layers...", 25)
    # ... do work
```
Dialog creates modal `QProgressDialog`, forwards to Logic's callback parameter.

### Layer Tree Operations
When manipulating project layers:
- Get layer order from `QgsLayerTreeRoot` before modifications
- Preserve auxiliary storage (label drags) via `preserve_auxiliary_tables` flag
- Use `QgsReadWriteContext` when reading/writing XML layer definitions
- Example in `MirrorProjectLogic.export_layers_to_projects()`

### Styling & Internationalization
- Icons: `Assets/img/CTD_logo.png` (used throughout)
- Translation: `i18n/` directory, strings wrapped with `self.tr()` in plugin/dialogs
- HTML Help: Inline HTML strings in `ctdprocessing_command_info` with styled font colors (`fop`, `foe`, `fcc`)

## Project-Specific Patterns

### Mirror Project Tool
Syncs layers/themes/layouts from master project to child projects:
- Preserves layer filters, auxiliary tables (label positions), and group hierarchy
- Creates backups before modification (optional)
- Uses XML serialization for layer transfer via `writeLayerXml()`

### Layers Advanced Tool
Dock widget (not dialog) providing enhanced layer management:
- Service-based architecture: `layer_service.py`, `visibility_service.py`
- Custom widgets: `layer_tree_widget.py`, `toolbar_widget.py`, `context_menu.py`
- Checkable action in menu toggles dock visibility

### Package Layer Updater
Updates geopackage layers from active project:
- Tracks modification history in attributes
- Optional FID duplicate fixing
- Skip unchanged layers option

## Important Constraints

### QGIS API Usage
- All QGIS imports from `qgis.core`, `qgis.gui`, or `qgis.PyQt`
- PyQt5 imports as fallback: `from PyQt5.QtWidgets import ...`
- Plugin lifecycle: `initGui()` → `initProcessing()` → ... → `unload()`

### Windows Development Focus
- Paths use Windows conventions but QGIS abstracts most platform differences
- PowerShell scripts for setup/deployment
- Batch files for compilation tasks

### Metadata & Versioning
- `metadata.txt`: Plugin metadata (version, description, dependencies)
- Version: Currently 0.5, marked as experimental
- Min QGIS version: 3.0
