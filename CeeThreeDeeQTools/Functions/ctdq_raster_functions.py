import os
import numpy as np
import heapq
from osgeo import gdal
from qgis.core import (    
    QgsProcessing,
    QgsRasterFileWriter,
    QgsRasterBlock,
    Qgis

)

class CtdqRasterFunctions:
    @staticmethod
    def ctdq_raster_fromNumpy(input_numpy,width,height,extent, crs, feedback,no_data_value: int=-32567):
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
    def ctdq_raster_fillsinks(input_raster, feedback):
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
                    return {}
                for x in range(width):
                    try:
                        value = block.value(x, y)
                    except Exception:
                        # Defensive: if block.value misbehaves, set nodata
                        value = None
                    dem[y, x] = float(value) if value is not None else -9999
                if (y % row_update) == 0:
                    try:
                        pct = int(5 + (y / float(height)) * 10)
                        feedback.setProgress(pct)
                    except Exception:
                        pass
        feedback.pushInfo(f"dem array shape after read: {dem.shape}, dtype: {dem.dtype}")
        
        # Sink-fill (priority queue propagation)
        pq = PriorityQueue()
        visited = np.zeros((height, width), dtype=bool)
        # add top and bottom rows
        for x in range(width):
            if dem[0, x] != no_data_value:
                pq.put((0, x), dem[0, x])
                visited[0, x] = True
            if dem[height - 1, x] != no_data_value:
                pq.put((height - 1, x), dem[height - 1, x])
                visited[height - 1, x] = True
        # add left and right columns
        for y in range(1, height - 1):
            if dem[y, 0] != no_data_value:
                pq.put((y, 0), dem[y, 0])
                visited[y, 0] = True
            if dem[y, width - 1] != no_data_value:
                pq.put((y, width - 1), dem[y, width - 1])
                visited[y, width - 1] = True

        # Main loop: process cells from the priority queue (row=y, col=x)
        filled_dem = dem.copy()
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # (dy, dx)
        # We'll track progress by processed nodes vs total cells as an estimate
        total_cells = float(max(1, height * width))
        processed = 0
        update_step = max(1, int(total_cells // 200))
        while not pq.empty():
            if feedback.isCanceled():
                feedback.pushInfo("Processing canceled during sink-fill step.")
                return {}
            y, x = pq.get()
            processed += 1
            for dy, dx in directions:
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    if not visited[ny, nx] and dem[ny, nx] != no_data_value:
                        if filled_dem[ny, nx] < filled_dem[y, x]:
                            filled_dem[ny, nx] = filled_dem[y, x]
                        pq.put((ny, nx), filled_dem[ny, nx])
                        visited[ny, nx] = True
            if (processed % update_step) == 0:
                try:
                    pct = int(15 + (processed / total_cells) * 35)
                    feedback.setProgress(min(90, pct))
                except Exception:
                    pass
       
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
        out_raster = driver.Create(temp_filled_path, width, height, 1, gdal.GDT_Float32)
        out_raster.SetGeoTransform(geotransform)
        out_raster.SetProjection(proj_wkt)
        out_band = out_raster.GetRasterBand(1)
        # Prepare filled_dem for writing and add diagnostics
        try:
            arr = np.ascontiguousarray(filled_dem.astype(np.float32))
        except Exception as e:
            feedback.reportError(f"Failed to prepare filled_dem array for writing: {e}")
            out_raster = None
            return {}
        feedback.pushInfo(f"filled_dem array shape: {arr.shape}, dtype: {arr.dtype}")
        try:
            xs = out_raster.RasterXSize
            ys = out_raster.RasterYSize
            feedback.pushInfo(f"GDAL out_raster size: xsize={xs}, ysize={ys}")
        except Exception:
            feedback.pushInfo("Could not read out_raster size for logging")
        # GDAL expects (rows, cols) == (height, width)
        if arr.shape != (height, width):
            feedback.reportError(f"filled_dem shape {arr.shape} does not match expected (height,width)=({height},{width}). Aborting write.")
            out_raster = None
            return {}
        try:
            out_band.WriteArray(arr)
        except Exception as e:
            feedback.reportError(f"Failed to WriteArray for filled raster: {e}; arr.shape={arr.shape}; expected (height,width)=({height},{width})")
            out_raster = None
            return {}
        out_band.SetNoDataValue(no_data_value)
        out_band.FlushCache()
        out_band.SetNoDataValue(no_data_value)
        out_band.FlushCache()
        # Readback verification: open written file and compare
        try:
            ds_check = out_raster
            if ds_check is not None:
                band_check = ds_check.GetRasterBand(1)
                arr_check = band_check.ReadAsArray()
                gt_check = ds_check.GetGeoTransform()
                feedback.pushInfo(f"Written raster readback shape: {arr_check.shape}, dtype: {arr_check.dtype}")
                feedback.pushInfo(f"Written raster geotransform: {gt_check}")
                # sample corners
                h_ck, w_ck = arr_check.shape
                sample_vals = {
                    'top_left': float(arr_check[0, 0]),
                    'top_right': float(arr_check[0, w_ck - 1]),
                    'bottom_left': float(arr_check[h_ck - 1, 0]),
                    'bottom_right': float(arr_check[h_ck - 1, w_ck - 1])
                }
                feedback.pushInfo(f"Written raster corner samples: {sample_vals}")
            else:
                feedback.pushInfo("Could not open written filled raster for readback verification")
        except Exception as e:
            feedback.pushInfo(f"Exception during filled raster readback verification: {e}")
        finally:
            out_raster = None
        feedback.pushInfo(f"Filled raster written to: {temp_filled_path}")
        
        # Return the filled_dem array for further processing
        return filled_dem