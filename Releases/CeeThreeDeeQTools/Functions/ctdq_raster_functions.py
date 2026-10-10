import os
import numpy as np
import heapq
import logging
from osgeo import gdal

LOGGER = logging.getLogger(__name__)

class CtdqRasterFunctions:
    @staticmethod
    def ctdq_raster_fromNumpy(input_numpy,width,height,extent, crs, feedback,no_data_value: int = -32567):
        try:
            """
            Creates a raster layer in qgsprocessing.temporaryfrom a numpy array and returns it.
            """

            # Create a temporary file path for the output raster
            import tempfile, uuid
            raster_output_path = os.path.join(tempfile.gettempdir(), f"raster_from_numpy_{uuid.uuid4().hex}.tif")

            # Use GDAL to create raster from numpy array (more reliable than QgsRasterFileWriter)
            driver = gdal.GetDriverByName('GTiff')
            out_raster = driver.Create(raster_output_path, width, height, 1, gdal.GDT_Float32)
            
            # Set geotransform from extent
            geotransform = (
                extent.xMinimum(),
                (extent.xMaximum() - extent.xMinimum()) / width,
                0,
                extent.yMaximum(),
                0,
                -(extent.yMaximum() - extent.yMinimum()) / height
            )
            out_raster.SetGeoTransform(geotransform)
            out_raster.SetProjection(crs.toWkt())
            
            out_band = out_raster.GetRasterBand(1)
            out_band.SetNoDataValue(no_data_value)
            
            # Write the numpy array to the raster
            try:
                arr = np.ascontiguousarray(input_numpy.astype(np.float32))
                feedback.pushInfo(f"Writing numpy array shape: {arr.shape}, dtype: {arr.dtype}")
                if arr.shape != (height, width):
                    feedback.reportError(f"Array shape {arr.shape} does not match expected (height,width)=({height},{width})")
                    out_raster = None
                    return None
                out_band.WriteArray(arr)
                out_band.FlushCache()
            except Exception as e:
                feedback.reportError(f"Failed to write numpy array to raster: {e}")
                out_raster = None
                return None
            
            # Clean up
            out_raster = None

            feedback.pushInfo(f"Raster created from numpy array at {raster_output_path}")
            return raster_output_path
        except Exception as e:
            feedback.reportError(f"Error in ctdq_raster_fromNumpy: {e}")
            return None

    @staticmethod
    def ctdq_raster_asnumpy(input_raster, feedback):
        """
        Reads the input raster into a numpy array and returns it.
        """
        provider = input_raster.dataProvider()
        extent = input_raster.extent()
        width = input_raster.width()
        height = input_raster.height()
        no_data_value = provider.sourceNoDataValue(1)

        # Read raster into a numpy array with shape (height, width).
        dem = np.zeros((height, width), dtype=np.float32)
        read_ok = False
        src_path = provider.dataSourceUri()
        try:            
            ds_in = gdal.Open(src_path)
            if ds_in is not None:
                band = ds_in.GetRasterBand(1)
                arr = band.ReadAsArray()
                if arr is not None:
                    feedback.pushInfo(f"GDAL ReadAsArray shape: {arr.shape}")
                    # Expect (rows, cols) == (height, width)
                    if arr.shape == (height, width):
                        dem = arr.astype(np.float32)
                        nd = band.GetNoDataValue()
                        if nd is not None:
                            dem[dem == nd] = no_data_value
                        read_ok = True
                    else:
                        feedback.pushInfo(f"GDAL array shape {arr.shape} does not match expected (height,width)=({height},{width}). Will fallback to provider.block().")
                ds_in = None
        except Exception as e:
            feedback.pushInfo(f"GDAL ReadAsArray failed: {e}; falling back to provider.block()")
        
        if not read_ok:
            feedback.pushInfo("Using provider.block fallback to build numpy DEM (slower)")
            block = provider.block(1, extent, width, height)
            # update progress every few rows to keep UI responsive
            row_update = max(1, height // 50)
            for y in range(height):
                if feedback.isCanceled():
                    feedback.pushInfo("Processing canceled during raster read.")
                    return None
                for x in range(width):
                    try:
                        value = block.value(x, y)
                    except Exception:
                        # Defensive: if block.value misbehaves, set nodata
                        value = None
                    dem[y, x] = float(value) if value is not None else -9999
                if (y % row_update) == 0:
                    feedback.setProgress(int(y / height * 100))
        
        feedback.pushInfo(f"dem array shape after read: {dem.shape}, dtype: {dem.dtype}")
        return dem

    @staticmethod
    def ctdq_raster_fillsinks(input_raster, feedback, return_raster_path=False):
        class PriorityQueue:
            def __init__(self):
                self.elements = []

            def empty(self):
                return not self.elements

            def put(self, item, priority):
                heapq.heappush(self.elements, (priority, item))

            def get(self):
                return heapq.heappop(self.elements)[1]
        """
        Reads the input raster into a numpy DEM, performs sink-filling using a priority queue,
        and writes the filled DEM to disk. Returns filled_dem, geotransform, and no_data_value.
        """
        provider = input_raster.dataProvider()
        extent = input_raster.extent()
        width = input_raster.width()
        height = input_raster.height()
        no_data_value = provider.sourceNoDataValue(1)
        
        # Handle case where NoData is not defined
        if no_data_value is None or no_data_value == 0:
            no_data_value = -32567
            feedback.pushInfo(f"No NoData value defined, using default: {no_data_value}")
        else:
            feedback.pushInfo(f"Using NoData value: {no_data_value}")

        # Read raster into a numpy array with shape (height, width).
        dem = np.zeros((height, width), dtype=np.float32)
        read_ok = False
        src_path = provider.dataSourceUri()
        try:            
            ds_in = gdal.Open(src_path)
            if ds_in is not None:
                band = ds_in.GetRasterBand(1)
                arr = band.ReadAsArray()
                if arr is not None:
                    feedback.pushInfo(f"GDAL ReadAsArray shape: {arr.shape}")
                    # Expect (rows, cols) == (height, width)
                    if arr.shape == (height, width):
                        dem = arr.astype(np.float32)
                        nd = band.GetNoDataValue()
                        if nd is not None:
                            # Mark NoData cells
                            dem[dem == nd] = no_data_value
                        read_ok = True
                    else:
                        feedback.pushInfo(f"GDAL array shape {arr.shape} does not match expected (height,width)=({height},{width}). Will fallback to provider.block().")
                ds_in = None
        except Exception as e:
            feedback.pushInfo(f"GDAL ReadAsArray failed: {e}; falling back to provider.block()")
        
        if not read_ok:
            feedback.pushInfo("Using provider.block fallback to build numpy DEM (slower)")
            block = provider.block(1, extent, width, height)
            # update progress every few rows to keep UI responsive
            row_update = max(1, height // 50)
            for y in range(height):
                if feedback.isCanceled():
                    feedback.pushInfo("Processing canceled during raster read.")
                    return None
                for x in range(width):
                    try:
                        value = block.value(x, y)
                    except Exception:
                        # Defensive: if block.value misbehaves, set nodata
                        value = None
                    dem[y, x] = float(value) if value is not None else no_data_value
                if (y % row_update) == 0:
                    try:
                        pct = int(5 + (y / float(height)) * 10)
                        feedback.setProgress(pct)
                    except Exception:
                        LOGGER.debug("Raster progress update failed", exc_info=True)
        
        feedback.pushInfo(f"DEM array shape after read: {dem.shape}, dtype: {dem.dtype}")
        
        # Count valid (non-NoData) cells
        valid_mask = (dem != no_data_value) & np.isfinite(dem)
        valid_count = np.sum(valid_mask)
        total_count = height * width
        feedback.pushInfo(f"Valid cells: {valid_count} / {total_count} ({100.0 * valid_count / total_count:.1f}%)")
        
        if valid_count == 0:
            feedback.reportError("No valid data cells found in raster!")
            return None
        
        # Sink-fill (priority queue propagation)
        pq = PriorityQueue()
        visited = np.zeros((height, width), dtype=bool)
        
        # Mark all NoData cells as visited so they are never processed
        visited[~valid_mask] = True
        
        # Initialize priority queue with boundary cells (edges of valid data)
        # Top and bottom rows
        for x in range(width):
            # Top row
            if valid_mask[0, x]:
                pq.put((0, x), dem[0, x])
                visited[0, x] = True
            # Bottom row
            if valid_mask[height - 1, x]:
                pq.put((height - 1, x), dem[height - 1, x])
                visited[height - 1, x] = True
        
        # Left and right columns (excluding corners already added)
        for y in range(1, height - 1):
            # Left column
            if valid_mask[y, 0]:
                pq.put((y, 0), dem[y, 0])
                visited[y, 0] = True
            # Right column
            if valid_mask[y, width - 1]:
                pq.put((y, width - 1), dem[y, width - 1])
                visited[y, width - 1] = True
        
        # Also add cells that border NoData as boundary cells
        # This ensures irregular boundaries are handled correctly
        feedback.pushInfo("Detecting interior boundaries adjacent to NoData...")
        interior_boundary_count = 0
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # (dy, dx)
        
        for y in range(1, height - 1):
            if feedback.isCanceled():
                return None
            for x in range(1, width - 1):
                # If this cell is valid and not yet visited
                if valid_mask[y, x] and not visited[y, x]:
                    # Check if any neighbor is NoData
                    has_nodata_neighbor = False
                    for dy, dx in directions:
                        ny, nx = y + dy, x + dx
                        if not valid_mask[ny, nx]:  # Neighbor is NoData
                            has_nodata_neighbor = True
                            break
                    
                    if has_nodata_neighbor:
                        # This is an interior boundary cell
                        pq.put((y, x), dem[y, x])
                        visited[y, x] = True
                        interior_boundary_count += 1
        
        feedback.pushInfo(f"Found {interior_boundary_count} interior boundary cells adjacent to NoData")
        
        # Initialize filled_dem with original values
        filled_dem = dem.copy()
        
        # Main loop: process cells from the priority queue
        processed = 0
        update_step = max(1, valid_count // 200)
        
        while not pq.empty():
            if feedback.isCanceled():
                feedback.pushInfo("Processing canceled during sink-fill step.")
                return None
            
            y, x = pq.get()
            processed += 1
            
            # Process neighbors
            for dy, dx in directions:
                ny, nx = y + dy, x + dx
                
                # Check bounds
                if 0 <= ny < height and 0 <= nx < width:
                    # Only process valid, unvisited cells
                    if valid_mask[ny, nx] and not visited[ny, nx]:
                        # If neighbor is lower than current cell, raise it
                        if filled_dem[ny, nx] < filled_dem[y, x]:
                            filled_dem[ny, nx] = filled_dem[y, x]
                        
                        # Add to queue and mark as visited
                        pq.put((ny, nx), filled_dem[ny, nx])
                        visited[ny, nx] = True
            
            # Update progress
            if (processed % update_step) == 0:
                try:
                    pct = int(15 + (processed / float(valid_count)) * 75)
                    feedback.setProgress(min(90, pct))
                except Exception:
                    LOGGER.debug("Raster sink-fill progress update failed", exc_info=True)
        
        feedback.pushInfo(f"Processed {processed} valid cells during sink-fill")
       
        # Write filled raster to disk using GDAL        
        driver = gdal.GetDriverByName('GTiff')

        # Try to preserve the source raster's exact GDAL geotransform and projection
        geotransform = None
        proj_wkt = None
        try:
            src_path = input_raster.dataProvider().dataSourceUri()
            ds_in = gdal.Open(src_path)
            if ds_in is not None:
                gt = ds_in.GetGeoTransform()
                if gt is not None:
                    geotransform = gt
                pw = ds_in.GetProjection()
                if pw:
                    proj_wkt = pw
                ds_in = None
        except Exception as e:
            feedback.pushInfo(f"Could not open source with GDAL to read geotransform/projection: {e}")

        # Fallback: compute a standard north-up geotransform using extent and pixel sizes
        if geotransform is None:
            extent = input_raster.extent()
            geotransform = (
                extent.xMinimum(),
                input_raster.rasterUnitsPerPixelX(),
                0,
                extent.yMaximum(),
                0,
                -input_raster.rasterUnitsPerPixelY()
            )
            feedback.pushInfo("Using computed north-up geotransform (source geotransform not available).")
        else:
            feedback.pushInfo(f"Using source GDAL geotransform: {geotransform}")

        if not proj_wkt:
            proj_wkt = input_raster.crs().toWkt()

        # Create a temporary file path for the filled raster
        import tempfile, uuid
        temp_filled_path = os.path.join(tempfile.gettempdir(), f"filled_raster_{uuid.uuid4().hex}.tif")
        
        try:
            out_raster = driver.Create(temp_filled_path, width, height, 1, gdal.GDT_Float32)
            out_raster.SetGeoTransform(geotransform)
            out_raster.SetProjection(proj_wkt)
            out_band = out_raster.GetRasterBand(1)
            out_band.SetNoDataValue(float(no_data_value))
            
            # Prepare filled_dem for writing
            arr = np.ascontiguousarray(filled_dem.astype(np.float32))
            feedback.pushInfo(f"Writing filled_dem array shape: {arr.shape}, dtype: {arr.dtype}")
            
            if arr.shape != (height, width):
                feedback.reportError(f"filled_dem shape {arr.shape} does not match expected (height,width)=({height},{width})")
                out_raster = None
                return None
            
            out_band.WriteArray(arr)
            out_band.FlushCache()
            
            # Verify write
            feedback.pushInfo(f"Filled raster written to: {temp_filled_path}")
            
        except Exception as e:
            feedback.reportError(f"Failed to write filled raster: {e}")
            if out_raster:
                out_raster = None
            return None
        finally:
            if out_raster:
                out_raster = None
        
        feedback.setProgress(100)
        
        if return_raster_path:
            return temp_filled_path

        # Preserve the original array-returning behavior for existing callers.
        return filled_dem

    @staticmethod
    def ctdq_raster_create_depression_mask(
        input_raster,
        filled_dem,
        feedback,
        minimum_depth=0.00001,
    ):
        """Create a GRASS depression map from a sink-filled DEM array."""
        dem = CtdqRasterFunctions.ctdq_raster_asnumpy(input_raster, feedback)
        if dem is None or filled_dem is None or dem.shape != filled_dem.shape:
            feedback.reportError("Cannot create depression mask from incompatible rasters.")
            return None

        no_data_value = input_raster.dataProvider().sourceNoDataValue(1)
        if no_data_value is None or no_data_value == 0:
            no_data_value = -32567
        valid_mask = (dem != no_data_value) & np.isfinite(dem) & np.isfinite(filled_dem)
        depth = filled_dem.astype(np.float32) - dem.astype(np.float32)
        depression_mask = np.where(
            valid_mask & (depth > float(minimum_depth)),
            1.0,
            no_data_value,
        ).astype(np.float32)

        depression_count = int(np.count_nonzero(depression_mask == 1.0))
        feedback.pushInfo(
            f"Created depression mask with {depression_count} cells "
            f"deeper than {minimum_depth:g}"
        )
        return CtdqRasterFunctions.ctdq_raster_fromNumpy(
            depression_mask,
            input_raster.width(),
            input_raster.height(),
            input_raster.extent(),
            input_raster.crs(),
            feedback,
            no_data_value=no_data_value,
        )

    @staticmethod
    def ctdq_raster_copy(input_path, output_path, feedback):
        """Copy a generated raster to a Processing output destination."""
        try:
            output_dataset = gdal.Translate(output_path, input_path, format="GTiff")
            if output_dataset is None:
                feedback.reportError(f"Could not write raster output: {output_path}")
                return None
            output_dataset = None
            return output_path
        except Exception as error:
            feedback.reportError(f"Could not copy raster output: {error}")
            return None

    @staticmethod
    def ctdq_raster_breach_depressions(
        input_raster,
        feedback,
        max_length=50,
        max_elevation_decrement=0.0,
        min_elevation_drop=0.0,
    ):
        """Breach local pits along bounded least-cost paths."""
        dem = CtdqRasterFunctions.ctdq_raster_asnumpy(input_raster, feedback)
        if dem is None:
            return None

        height, width = dem.shape
        provider = input_raster.dataProvider()
        no_data_value = provider.sourceNoDataValue(1)
        if no_data_value is None or no_data_value == 0:
            no_data_value = -32567

        valid_mask = (dem != no_data_value) & np.isfinite(dem)
        if not np.any(valid_mask):
            feedback.reportError("No valid data cells found in raster!")
            return None

        max_length = max(1, int(max_length))
        max_cost = float(max_elevation_decrement)
        z_range = float(np.nanmax(dem[valid_mask]) - np.nanmin(dem[valid_mask]))
        zdrop = float(min_elevation_drop) if min_elevation_drop > 0 else max(z_range * 1e-7, 1e-5)
        directions = [
            (-1, -1, 2 ** 0.5), (-1, 0, 1.0), (-1, 1, 2 ** 0.5),
            (0, -1, 1.0), (0, 1, 1.0),
            (1, -1, 2 ** 0.5), (1, 0, 1.0), (1, 1, 2 ** 0.5),
        ]
        breached_dem = dem.copy()
        pits = []

        for y in range(1, height - 1):
            for x in range(1, width - 1):
                if not valid_mask[y, x]:
                    continue
                elevation = breached_dem[y, x]
                if all(
                    not valid_mask[y + dy, x + dx]
                    or breached_dem[y + dy, x + dx] >= elevation
                    for dy, dx, _ in directions
                ):
                    pits.append((y, x))

        feedback.pushInfo(
            f"Detected {len(pits)} pit cells; maximum breach length: {max_length} cells"
        )
        solved = 0

        for pit_index, (pit_y, pit_x) in enumerate(pits):
            if feedback.isCanceled():
                return None
            pit_elevation = breached_dem[pit_y, pit_x]
            if any(
                valid_mask[pit_y + dy, pit_x + dx]
                and breached_dem[pit_y + dy, pit_x + dx] < pit_elevation
                for dy, dx, _ in directions
            ):
                continue

            min_y = max(0, pit_y - max_length)
            max_y = min(height - 1, pit_y + max_length)
            min_x = max(0, pit_x - max_length)
            max_x = min(width - 1, pit_x + max_length)
            costs = {}
            previous = {}
            queue = []

            for target_y in range(min_y, max_y + 1):
                for target_x in range(min_x, max_x + 1):
                    if not valid_mask[target_y, target_x]:
                        continue
                    distance = max(abs(target_y - pit_y), abs(target_x - pit_x))
                    if distance == 0 or distance > max_length:
                        continue
                    target_elevation = breached_dem[target_y, target_x]
                    local_cost = max(0.0, target_elevation - pit_elevation) + distance * zdrop
                    if target_elevation + distance * zdrop < pit_elevation:
                        costs[(target_y, target_x)] = 0.0
                        heapq.heappush(queue, (0.0, target_y, target_x))
                    elif max_cost <= 0.0 or local_cost <= max_cost:
                        costs[(target_y, target_x)] = float("inf")

            centre = (pit_y, pit_x)
            costs[centre] = float("inf")
            while queue:
                cost, current_y, current_x = heapq.heappop(queue)
                if cost != costs.get((current_y, current_x)):
                    continue
                if (current_y, current_x) == centre:
                    break
                for dy, dx, distance in directions:
                    next_cell = (current_y + dy, current_x + dx)
                    next_y, next_x = next_cell
                    if next_cell not in costs:
                        continue
                    next_cost = cost + (
                        max(0.0, breached_dem[current_y, current_x] - pit_elevation)
                        + max(0.0, breached_dem[next_y, next_x] - pit_elevation)
                    ) * 0.5 * distance
                    if next_cost < costs[next_cell]:
                        costs[next_cell] = next_cost
                        previous[next_cell] = (current_y, current_x)
                        heapq.heappush(queue, (next_cost, next_y, next_x))

            if centre not in previous:
                continue

            path = []
            cell = centre
            while cell != (pit_y, pit_x):
                path.append(cell)
                cell = previous[cell]
            previous_elevation = pit_elevation
            for path_y, path_x in path:
                breached_dem[path_y, path_x] = min(
                    breached_dem[path_y, path_x], previous_elevation - zdrop
                )
                previous_elevation = breached_dem[path_y, path_x]
            solved += 1

            if pit_index % max(1, len(pits) // 100) == 0:
                feedback.setProgress(int(15 + 70 * pit_index / max(1, len(pits))))

        feedback.pushInfo(f"Breached {solved} of {len(pits)} detected pit cells")

        geotransform = None
        projection = None
        source_path = provider.dataSourceUri()
        try:
            source_dataset = gdal.Open(source_path)
            if source_dataset is not None:
                geotransform = source_dataset.GetGeoTransform()
                projection = source_dataset.GetProjection()
                source_dataset = None
        except Exception as error:
            feedback.pushInfo(f"Could not read source raster metadata: {error}")
        if geotransform is None:
            extent = input_raster.extent()
            geotransform = (
                extent.xMinimum(), input_raster.rasterUnitsPerPixelX(), 0,
                extent.yMaximum(), 0, -input_raster.rasterUnitsPerPixelY()
            )
        if not projection:
            projection = input_raster.crs().toWkt()

        import tempfile, uuid
        output_path = os.path.join(
            tempfile.gettempdir(), f"breached_raster_{uuid.uuid4().hex}.tif"
        )
        output_dataset = gdal.GetDriverByName("GTiff").Create(
            output_path, width, height, 1, gdal.GDT_Float32
        )
        output_dataset.SetGeoTransform(geotransform)
        output_dataset.SetProjection(projection)
        output_band = output_dataset.GetRasterBand(1)
        output_band.SetNoDataValue(float(no_data_value))
        output_band.WriteArray(np.ascontiguousarray(breached_dem.astype(np.float32)))
        output_band.FlushCache()
        output_dataset = None
        feedback.setProgress(100)
        feedback.pushInfo(f"Breached raster written to: {output_path}")
        return output_path