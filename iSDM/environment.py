
"""
A module for all environmental layers functionality.

      .. moduleauthor:: Daniela Remenska <remenska@gmail.com>

"""

import logging
from enum import Enum
import pprint
from rasterio.warp import calculate_default_transform, RESAMPLING
# from iSDM.species import IUCNSpecies
import numpy as np
from geopandas import GeoSeries, GeoDataFrame
import rasterio
from rasterio.transform import Affine
import matplotlib.pyplot as plt
from mpl_toolkits.basemap import Basemap
import pandas as pd
from shapely.geometry import Point
from matplotlib.collections import PatchCollection
from descartes import PolygonPatch
import shapely
from rasterio import features
from shapely.geometry import Polygon
import gc

logger = logging.getLogger('iSDM.environment')
logger.setLevel(logging.DEBUG)


class Source(Enum):
    """
    Possible sources of global environmental data.
    """
    WORLDCLIM = 1
    GLOBE = 2
    UNKNOWN = 3
    TNC = 4
    ARCGIS = 5
    WWL = 6


class EnvironmentalLayer(object):
    """
    EnvironmentalLayer
    A generic EnvironmentalLayer class used for subclassing different global-scale environmental data sources.

    :ivar source: The source of the global environmental data.
    :vartype source: iSDM.environment.Source

    :ivar name_layer: Description of the layer
    :vartype name_layer: string

    """
    def __init__(self, source=None, file_path=None, name_layer=None, **kwargs):
        if source:
            if not isinstance(source, Source):
                raise AttributeError("The source can only be one of the following: %s " % list(Source.__members__))
            self.source = source
        else:
            self.source = Source.UNKNOWN
        if file_path:
            self.file_path = file_path
        self.name_layer = name_layer

    def load_data(self, file_path=None):
        """
        Needs to be implemented in a subclass.
        """
        raise NotImplementedError("You need to implement this method in a subclass!")

    def set_source(self, source):
        if not isinstance(source, Source):
            raise AttributeError("The source can only be one of the following: %s " % list(Source.__members__))
        self.source = source

    def get_source(self):
        return self.source.name

    def save_data(self, full_name=None, dir_name=None, file_name=None):
        """
        Needs to be implemented in a subclass.
        """
        raise NotImplementedError("You need to implement this method in a subclass!")

    def get_data(self):
        """
        Needs to be implemented in a subclass.
        """
        raise NotImplementedError("You need to implement this method in a subclass!")


class RasterEnvironmentalLayer(EnvironmentalLayer):
    """
    RasterEnvironmentalLayer

    A class for encapsulating the raster environmental layer functionality. Operations such as reprojecting,
    overlaying, sampling pseudo-absence pixels, converting to world map coordinates, are some of the functionalities
    implemented as wrappers around corresponding rasterio/Numpy operations and methods.
    This class should be used when the expected layer data is in raster format, i.e., 2-dimensional (multi-band) array of data.

    :ivar file_path: Location of the raster file from which the raster map data is loaded.
    :vartype file_path: string

    :ivar raster_affine: Affine translation used in the environmental raster map.
    :vartype raster_affine: rasterio.transform.Affine

    :ivar resolution: The resolution of the raster map, as a tuple (height, width) in pixels.
    :vartype resolution: tuple(int, int)

    :ivar raster_reader: file reader for the corresponding rasterized data.
    :vartype raster_reader: rasterio._io.RasterReader

    """
    def __init__(self, source=None, file_path=None, name_layer=None, **kwargs):
        EnvironmentalLayer.__init__(self, source, file_path, name_layer, **kwargs)

    def load_data(self, file_path=None):
        """
        Loads the raster data from a previously-saved raster file. Provides information about the
        loaded data, and returns a rasterio file reader handle, which allows you to read individual raster bands.

        :param string file_path: The full path to the targed GeoTIFF raster file (including the directory and filename in one string).

        :returns: Rasterio RasterReader file object which can be used to read individual bands from the raster file.

        :rtype: rasterio._io.RasterReader

        """
        if file_path:
            self.file_path = file_path
        if not self.file_path:
            raise AttributeError("Please provide a file_path to read raster environment data from.")

        src = rasterio.open(self.file_path)
        logger.info("Loaded raster data from %s " % self.file_path)
        logger.info("Driver name: %s " % src.driver)
        pp = pprint.PrettyPrinter(depth=5)
        self.metadata = src.meta
        logger.info("Metadata: %s " % pp.pformat(self.metadata))
        logger.info("Resolution: x_res={0} y_res={1}.".format(src.width, src.height))
        logger.info("Bounds: %s " % (src.bounds,))
        logger.info("Coordinate reference system: %s " % src.crs)
        logger.info("Affine transformation: %s " % (src.affine.to_gdal(),))
        logger.info("Number of layers: %s " % src.count)
        logger.info("Dataset loaded. Use .read() or .read_masks() to access the layers.")
        self.raster_affine = src.affine
        self.resolution = src.res
        self.bounds = src.bounds
        self.raster_reader = src
        return self.raster_reader

    def pixel_to_world_coordinates(self,
                                   raster_data=None,
                                   filter_no_data_value=True,
                                   no_data_value=0,
                                   band_number=1):
        """
        Map the pixel coordinates to world coordinates. The affine transformation matrix is used for this purpose.
        The convention is to reference the pixel corner. To reference the pixel center instead, we translate each pixel by 50%.
        The "no value" pixels (cells) can be filtered out.

        A dataset's pixel coordinate system has its origin at the "upper left" (imagine it displayed on your screen).
        Column index increases to the right, and row index increases downward. The mapping of these coordinates to
        "world" coordinates in the dataset's reference system is done with an affine transformation matrix.

        param string raster_data: the raster data (2-dimensional array) to translate to world coordinates. If not provided, \
        it tries to load existing rasterized data about the RasterEnvironmentalLayer.

        :param int no_data_value: The pixel values depicting non-burned cells. Default is 0.

        :param bool filter_no_data_value: Whether to filter-out the no-data pixel values. Default is true. If set to \
        false, all pixels in a 2-dimensional array will be converted to world coordinates. Typically this option is used \
        to get a "base" map of the coordinates of all pixels in an image (map).

        :returns: A tuple of numpy ndarrays. The first array contains the latitude values for each \
        non-zero cell, the second array contains the longitude values for each non-zero cell.

        TODO: document raster-affine

        :rtype: tuple(np.ndarray, np.ndarray)

        """
        if raster_data is None:
            logger.info("No raster data provided, attempting to load default...")
            try:
                raster_data = self.load_data(self.file_path).read(band_number)  # we work on one layer, the first
                logger.info("Succesfully loaded existing raster data from %s." % self.file_path)
            except AttributeError as e:
                logger.error("Could not open raster file. %s " % str(e))
                raise AttributeError(e)

        logger.info("Transforming to world coordinates...")
        # first get the original Affine transformation matrix
        if hasattr(self, "raster_affine"):
            T0 = self.raster_affine
        else:   # default from arguments
            # try to deduce it
            logger.info("No Affine translation defined for this layer, trying to deduce it.")
            x_min, y_min, x_max, y_max = -180, -90, 180, 90
            pixel_size = (x_max - x_min) / raster_data.shape[1]
            if pixel_size != (y_max - y_min) / raster_data.shape[0]:
                logger.error("Could not deduce Affine transformation...possibly the pixel is not a square.")
                return
            T0 = Affine(pixel_size, 0.0, x_min, 0.0, -pixel_size, y_max)
        # convert it to gdal format (it is otherwise flipped)
        T0 = Affine(*reversed(T0.to_gdal()))
        logger.debug("Affine transformation T0:\n %s " % (T0,))
        # shift by 50% to get the pixel center
        T1 = T0 * Affine.translation(0.5, 0.5)
        # apply the shift, filtering out no_data_value values
        logger.debug("Raster data shape: %s " % (raster_data.shape,))
        logger.debug("Affine transformation T1:\n %s " % (T1,))
        if filter_no_data_value:
            logger.info("Filtering out no_data pixels.")
            raster_data = np.where(raster_data != no_data_value, raster_data, np.nan)
            coordinates = (T1 * np.where(~np.isnan(raster_data)))
        else:
            coordinates = (T1 * np.where(raster_data))
        logger.info("Transformation to world coordinates completed.")
        return coordinates

    @classmethod
    def __geometrize__(cls,
                       data,
                       latitude_col_name='decimallatitude',
                       longitude_col_name='decimallongitude',
                       crs=None,
                       dropna=True):
        """
        Private helper class function.
        Converts data from pandas.DataFrame contents to geopandas.GeoDataFrame format.
        GeoDataFrames inherit basic DataFrames, and provide more functionality on top of pandas.
        The biggest difference in terms of the data layout is the addition of a 'geometry' column which contains
        `Shapely <http://toblerity.org/shapely/shapely.geometry.html>`_ geometries in `geopandas <http://geopandas.org/user.html>`_.
        The decimallatitude and decimallongitude columns are converted into shapely Point geometry, one Point for each latitude/longitude
        record.

        :param bool dropna: Whether to drop records with NaN values in the decimallatitude or decimallongitude columns in the conversion process.

        :param string longitude_col_name: The name of the column carrying the decimal longitude values. Default is 'decimallongitude'.

        :param string latitude_col_name: The name of the column carrying the decimal latitude values. Default is 'decimallatitude'

        :param crs: The Coordinate Reference System of the data. Default is "EPSG:4326"
        :type crs: string or dictionary.

        :returns: geopandas.GeoDataFrame

        """
        if not isinstance(data, pd.DataFrame) or not data:
            logger.info("Please provide the data parameter as a pandas.DataFrame.")
            return

        try:
            if crs is None:
                crs = {'init': "EPSG:4326"}
            # exclude those points with NaN in plot_world_coordinates
            if dropna:
                geometry = [Point(xy) for xy in zip(
                    data[longitude_col_name].dropna(),
                    data[latitude_col_name].dropna()
                )]
                data_geo = GeoDataFrame(
                    data.dropna(
                        subset=[latitude_col_name, longitude_col_name]),
                    crs=crs,
                    geometry=geometry)
                logger.info("Data geometrized: converted into GeoPandas dataframe.")
                logger.info("Points with NaN coordinates ignored. ")
            else:
                geometry = [Point(xy) for xy in zip(
                    data[longitude_col_name],
                    data[latitude_col_name]
                )]
                data_geo = GeoDataFrame(data, crs=crs, geometry=geometry)
                logger.info("Data geometrized: converted into GeoPandas dataframe.")
        except AttributeError:
            logger.error("No latitude/longitude data to convert into a geometry. Please load the data first.")
        return data_geo

    def polygonize(self, band_number=1):
        """
        Extract shapes from raster features. This is the inverse operation of rasterizing shapes.
        Uses the `Rasterio <https://mapbox.github.io/rasterio/_modules/rasterio/features.html>'_ library
        for this purpose. The data is loaded into a `geopandas <http://geopandas.org/user.html>`_ GeoDataFrame.
        GeoDataFrame data structures are pandas DataFrames with added functionality, containing a ``geometry``
        column for the `Shapely <http://toblerity.org/shapely/shapely.geometry.html>`_ geometries.
        The raster data should be loaded in the layer before calling this method.

        :param int band_number: The index of the raster band which is to be used as input for extracting \
        gemetrical shapes.

        :returns: geopandas.GeoDataFrame

        """
        raster_data = self.read(band_number)
        mask = raster_data != self.raster_reader.nodata
        T0 = self.raster_reader.affine
        shapes = features.shapes(raster_data, mask=mask, transform=T0)
        df = GeoDataFrame.from_records(shapes, columns=['geometry', 'value'])
        # convert the geometry dictionary from a dictionary format like {'coordinates': [[(-73.5, 83.5),
        #   (-73.5, 83.0),
        #   (-68.0, 83.0),
        #   (-68.0, 83.5),
        #   (-73.5, 83.5)]],
        # 'type': 'Polygon'}
        # to a proper shapely polygon format
        df.geometry = df.geometry.apply(lambda row: Polygon(row['coordinates'][0]))
        df.crs = self.raster_reader.crs
        return df

    @classmethod
    def plot_world_coordinates(cls,
                               coordinates=None,
                               figsize=(16, 12),
                               projection='merc',
                               facecolor='crimson'):
        """
        Visually plots coordinates on a `Basemap <http://matplotlib.org/basemap/api/basemap_api.html#module-mpl_toolkits.basemap>`_.
        Basemap supports projections (with coastlines and political boundaries) using matplotlib.
        The coordinates data must be provided as a tuple of Numpy arrays, one for the x, and one for the y values of the coordinates.
        First, the data is converted to a ``pandas.DataFrame`` with the x and y arrays transposed as ``decimallatitude`` and ``decimallongitude``
        columns.
        Next, the :func:`__geometrize__` method is used to convert the dataframe into a geoopandas format (with a ``geometry`` column).

        :param tuple coordinates: A tuple containing Numpy arrays, one for the x, and one for the y values of the coordinates.

        :param tuple figsize: A tuple containing the (width, height) of the plot, in inches. Default is (16, 12)

        :param string projection: The projection to use for plotting. Supported projection values from
        `Basemap <http://matplotlib.org/basemap/api/basemap_api.html#module-mpl_toolkits.basemap>`_. Default is 'merc' (Mercator)

        :param string facecolor: Fill color for the geometries. Defaylt is "crimson" (red)

        :returns: a map with geometries plotted, zoomed to the total boundaries of the geometry Series (column) of the DataFrame.

        """
        if coordinates is None or not isinstance(coordinates, tuple) \
           or not isinstance(coordinates[0], np.ndarray) \
           or not isinstance(coordinates[1], np.ndarray):
            logger.error("Please provide the coordinates to plot, in the correct format.")
            logger.error("Use pixel_to_world_coordinates() for this.")
            return
        # empty dataset
        if coordinates[0].shape[0] == 0:
            logger.error("No data to plot.")
            return
        data = pd.DataFrame([coordinates[0], coordinates[1]]).T
        data.columns = ['decimallatitude', 'decimallongitude']
        data_geometrized = cls.__geometrize__(data)

        mm = Basemap(projection=projection, lat_0=50, lon_0=-100,
                     resolution='l', area_thresh=1000.0,
                     llcrnrlon=data_geometrized.geometry.total_bounds[0],  # lower left corner longitude point
                     llcrnrlat=data_geometrized.geometry.total_bounds[1],  # lower left corner latitude point
                     urcrnrlon=data_geometrized.geometry.total_bounds[2],  # upper right longitude point
                     urcrnrlat=data_geometrized.geometry.total_bounds[3]   # upper right latitude point
                     )

        # prepare longitude/latitude list for basemap
        ax1 = plt.subplots(figsize=figsize)[1]

        plt.title("World coordinates of raster data.")

        mm.drawcoastlines()
        mm.drawcountries()
        mm.drawrivers(color='lightskyblue', linewidth=1.5)
        mm.drawmapboundary(fill_color='lightskyblue')
        mm.fillcontinents(color='cornsilk')
        # draw latitude and longitude
        mm.drawmeridians(np.arange(-180, 180, 10), labels=[False, False, False, True])
        mm.drawparallels(np.arange(-180, 180, 10), labels=[True, True, False, False])

        patches = []
        selection = data_geometrized
        for poly in selection.geometry:
            if poly.geom_type == 'Polygon':
                mpoly = shapely.ops.transform(mm, poly)
                patches.append(PolygonPatch(mpoly))
            elif poly.geom_type == 'MultiPolygon':
                for subpoly in poly:
                    mpoly = shapely.ops.transform(mm, subpoly)
                    patches.append(PolygonPatch(mpoly))
            elif poly.geom_type == "Point":
                patches.append(PolygonPatch(Point(mm(poly.x, poly.y)).buffer(9999)))  # TODO: this buffer thing is tricky around the edges of a map
            else:
                logger.warning("Geometry type %s not supported. Skipping ... " % poly.geom_type)
                continue
        ax1.add_collection(PatchCollection(patches, facecolor=facecolor, match_original=True, zorder=100))
        plt.show()

    def plot(self, figsize=(25, 20), band_number=1):
        """
        A simple plot of the raster image data. The data should be loaded before calling this method.

        :param tuple figsize: A tuple containing the (width, height) of the plot, in inches. Default is (25, 20)

        :param int band_number: The index of the band to use for plotting the raster data.

        """
        if not self.raster_reader or self.raster_reader.closed:
            logger.info("The dataset is closed. Please load it first using .load_data()")
            return
        plt.figure(figsize=figsize)
        plt.title(self.name_layer)
        plt.imshow(self.read(band_number), cmap="flag", interpolation="none")

    def close_dataset(self):
        """
        Close the ``rasterio._io.RasterReader`` file reader, if open. This releases resources such as memory.
        """
        if not self.raster_reader.closed:
            self.raster_reader.close()
            logger.info("Dataset %s closed. " % self.file_path)

    def get_data(self):
        """
        :returns: A raster file reader, from which any band data can be read using .read(band_number)

        :rtype: rasterio._io.RasterReader

        """
        if not self.raster_reader or self.raster_reader.closed:
            logger.info("The dataset is closed. Please load it first using .load_data()")
            return
        return self.raster_reader

    def read(self, band_number=1):
        """
        Read a particular band from the raster data array.

        :param int band_number: The index of the band to read.

        :returns: A 2-dimensional Numpy array containing the pixel values of that particular band.

        """
        if not hasattr(self, 'raster_reader'):
            raise AttributeError("Please load the data first, using .load_data()")
        if not self.raster_reader or self.raster_reader.closed:
            logger.info("The dataset is closed. Please load it first using .load_data()")
            return
        return self.raster_reader.read(band_number)

    def reproject(self, destination_file, source_file=None, resampling=RESAMPLING.nearest, **kwargs):
        """
        Reprojects the pixels of a source raster map to a destination raster, with a different reference coordinate
        system and Affine transform. It uses `Rasterio <https://github.com/mapbox/rasterio/blob/master/docs/reproject.rst>`_
        calculate_default_transform() to calculate parameters such as the resolution (if not provided), and the destination
        transform and dimensions.

        param string source_file: Full path to the source file containing a raster map

        param string destination_file: Full path to the destination file containing a raster map

        :param int resampling: Resampling method to use. Can be one of the following: ``Resampling.nearest``, ``Resampling.bilinear``, \
        ``Resampling.cubic``, ``Resampling.cubic_spline``, ``Resampling.lanczos``, ``Resampling.average``, ``Resampling.mode``.

        :param dict kwargs: Optional additional arguments passed to the method, to parametrize the reprojection. \
        For example: :attr:`dst_crs` for the target coordinate reference system, :attr:`resolution` for the target resolution, \
        in units of target coordinate reference system.

        """
        if not source_file:
            if not self.file_path:
                raise AttributeError("Please provide a source_file to load the data from.")
            else:
                source_file = self.file_path

        with rasterio.open(source_file) as src:
            affine, width, height = calculate_default_transform(src_crs=src.crs,
                                                                dst_crs=kwargs.get('dst_crs', src.crs),
                                                                width=kwargs.get('width', src.width),
                                                                height=kwargs.get('height', src.height),
                                                                left=kwargs.get('left', src.bounds.left),
                                                                bottom=kwargs.get('bottom', src.bounds.bottom),
                                                                right=kwargs.get('right', src.bounds.right),
                                                                top=kwargs.get('top', src.bounds.top),
                                                                resolution=kwargs.get('resolution', src.res)
                                                                )
            logger.info("Calculated default transformation:")
            logger.info("Affine:\n{0} \n width={1}, height={2}".format(affine, width, height))

            kwargs = src.meta.copy()
            kwargs.update({'transform': affine,
                           'affine': affine,
                           'width': width,
                           'height': height
                           })

            with rasterio.open(destination_file, 'w', **kwargs) as dst:
                for i in range(1, src.count + 1):
                    rasterio.warp.reproject(source=rasterio.band(src, i),
                                            destination=rasterio.band(dst, i),
                                            src_transform=src.affine,
                                            src_crs=src.crs,
                                            dst_transform=affine,
                                            dst_crs=kwargs.get('dst_crs', src.crs),
                                            resampling=resampling
                                            )
            logger.info("Reprojected data in %s " % destination_file)

    # def overlay(self, range_map):
    #     """
    #     Extract mask from a raster map, where it intersects with a vector feature, like a polygon.
    #     rasterio provides option to "burn" vector shapes into rasters (rasterize the geometry). Then we create
    #     a raster mask layer
    #     """
    #     if not (isinstance(range_map, VectorEnvironmentalLayer) or isinstance(range_map, IUCNSpecies)):
    #         raise AttributeError("Please provide a correct rangemap input.")

    #     # TODO: what about if the overlay is just a shape file?
    #     # TODO: what if there are multiple geometries in a shapefile? Currently it just returns the last
    #     # but could make a list and append
    #     masked_data = None

    #     if isinstance(range_map, VectorEnvironmentalLayer) or isinstance(range_map, IUCNSpecies):
    #         for geometry in range_map.get_data()['geometry']:
    #             if self.raster_reader.closed:
    #                 self.load_data(self.file_path)
    #             with self.raster_reader as raster:
    #                 # get pixel coordinates of the geometry's bounding box
    #                 ul = raster.index(*geometry.bounds[0:2])
    #                 lr = raster.index(*geometry.bounds[2:4])

    #                 # read the subset of the data into a numpy array
    #                 window = ((lr[0], ul[0] + 1), (ul[1], lr[1] + 1))
    #                 data = raster.read(1, window=window)
    #                 # create an affine transform for the subset data
    #                 t = raster.affine
    #                 shifted_affine = Affine(t.a, t.b, t.c + ul[1] * t.a, t.d, t.e, t.f + lr[0] * t.e)
    #                 # rasterize the geometry
    #                 mask = features.rasterize(
    #                     [(geometry, 0)],
    #                     out_shape=data.shape,
    #                     transform=shifted_affine,
    #                     fill=1,
    #                     all_touched=True,
    #                     dtype=np.uint8)

    #                 # create a masked numpy array
    #                 masked_data = np.ma.array(data=data, mask=mask.astype(bool))

    #     self.masked_data = masked_data
    #     logger.info("Overlayed raster climate data with the given range map.")
    #     logger.info("Use the .masked_data attribute to access it.")

    def sample_pseudo_absences(self,
                               species_raster_data,
                               suitable_habitat=None,
                               bias_grid=None,
                               band_number=1,
                               number_of_pseudopoints=1000):
        """
        Samples a :attr:`number_of_pseudopoints` points from the ``RasterEnvironmentalLayer`` data (raster map),
        based on a given species raster map which is assumed to contain species presence points (or potential presence).
        The :attr:`species_raster_data` is used to determine which distinct regions (cell values) from the entire
        environmental raster map, should be taken into account for potential pseudo-absence sampling regions. In other words,
        which realms or ecoregions should be taken into account.
        Optionally, suitable habitat raster (with binary, 0/1s values) can be provided to further limit the area of sampling.
        Finally, presence pixels are removed from this map, and the resulting pixels are used as a base for sampling
        pseudo-absences. Optionally, a bias grid can be provided to bias the "random" sampling of pseudo absences.
        If the number of such resulting pixels left is smaller than the number of requested pseudo-absence
        points, all pixels are automatically taken as pseudo-absence points, and no random sampling is done.

        Otherwise, :attr:`number_of_pseudopoints` pixels positions (indices) are randomly chosen at once (for speed),
        rather than randomly sampling one by one until the desired number of pseudo-absences is reached.

        :param np.ndarray species_raster_data: A raster map containing the species presence pixels. If not provided, \
        by default the one loaded previously (if available, otherwise .load_data() should be used before) is used.

        :param np.ndarray suitable_habitat: A raster map containing the species suitable habitat. It should contain only \
        values of 0 and 1, 1s depicting a suitable areas, while 0s unsuitable.

        :param np.ndarray bias_grid: A raster map containing the sampling bias grid. It should contain integer values depicting \
        a sampling intensity at every pixel location.

        :param int band_number: The index of the band from the :attr:`species_raster_data` to use as input. Default is 1.

        :param int number_of_pseudopoints: Number of pseudo-absence points to sample from the raster environmental layer data.

        :returns: A tuple containing two raster maps, one with all potential background pixels chosen to sample from, \
        and second with all the actual sampled pixels.

        :rtype: tuple(np.ndarray, np.ndarray)

        """
        if not (isinstance(species_raster_data, np.ndarray)) or not (set(np.unique(species_raster_data)) == set({0, 1})):
            logger.error("Please provide the species raster data as a numpy array with pixel values 1 and 0 (presence/absence).")
            return
        if self.raster_reader.closed or not hasattr(self, 'env_raster_data'):
            try:
                self.env_raster_data = self.read(band_number)
                logger.info("Succesfully loaded existing raster data from %s." % self.file_path)
            except AttributeError as e:
                logger.error("Could not open raster file. %s " % str(e))
        if species_raster_data.shape != self.env_raster_data.shape:
            logger.error("Please provide (global) species raster data at the same resolution as the environment")
            logger.error("Environment data has the following shape %s " % (self.env_raster_data.shape, ))
            return

        logger.info("Sampling %s pseudo-absence points from environmental layer." % number_of_pseudopoints)
        # first set to zero all pixels that have "nodata" values in the environmental raster
        self.env_raster_data[self.env_raster_data == self.raster_reader.nodata] = 0
        # next get all the overlapping pixels between the species raster and the environment data
        presences_pixels = self.env_raster_data * species_raster_data
        # what are the unique values left? (these are the distinct "regions" that need to be taken into account)
        # Do NOT take into account the 0-value pixel, which we assigned to all "nodata" pixels
        unique_regions = np.unique(presences_pixels[presences_pixels != 0])
        if len(unique_regions) == 0:
            logger.info("There are no environmental layers to sample pseudo-absences from. ")
            return (np.zeros_like(presences_pixels), np.zeros_like(presences_pixels))
        logger.debug("The following unique (region ID) values will be taken into account for sampling pseudo-absences")
        logger.debug(unique_regions)
        # add the pixels of all these regions to a layer array
        regions = []
        for region in unique_regions:
            regions.append(np.where(self.env_raster_data == region))
        # now "regions" contains a list of tuples, each tuple with separate x/y indexes (arrays thereof) of the pixels
        # make an empty "base" matrix and fill it with the selected regions pixel values
        selected_pixels = np.zeros_like(self.env_raster_data)
        # pick out only those layers that have been selected and fill in the matrix
        for layer in regions:
            selected_pixels[layer] = self.env_raster_data[layer]

        del regions
        gc.collect()
        # sample from those pixels which are in the selected raster regions, minus those of the species presences
        pixels_to_sample_from = selected_pixels - presences_pixels
        del presences_pixels
        sampled_pixels = np.zeros_like(selected_pixels)
        del selected_pixels
        gc.collect()

        # next: narrow the area to sample from, to the suitable habitat, if raster data is provided
        if suitable_habitat is not None:
            logger.info("Will limit sampling area to suitable habitat.")
            # Multiplying the suitable habitat layer (with 1s and 0s) with the
            # previously selected pixels, will narrow to those common for both.
            pixels_to_sample_from = pixels_to_sample_from * suitable_habitat

        # magic, don't touch :P
        if bias_grid is not None:
            logger.info("Will use the provided bias_grid for sampling.")
            # common x/y coordinates where bias_grid overlaps with pixels_to_sample_from
            (x, y) = np.where(pixels_to_sample_from * bias_grid > 0)
            # how many we have?
            number_pixels_to_sample_from_bias_grid = x.shape[0]
            logger.info("There are %s nonzero pixels from bias grid to use for sampling." % number_pixels_to_sample_from_bias_grid)
            if number_pixels_to_sample_from_bias_grid == 0:
                logger.info("No non-zero pixels from bias grid to sample.")
            if number_pixels_to_sample_from_bias_grid < number_of_pseudopoints:
                logger.info("Will sample all %s nonzero pixels from bias grid." % number_pixels_to_sample_from_bias_grid)
                # "random" here is not so random as we will select all of them, i.e., the entire range
                random_indices = np.arange(0, number_pixels_to_sample_from_bias_grid)
                for position in random_indices:
                    sampled_pixels[x[position]][y[position]] = pixels_to_sample_from[x[position], y[position]]
                # remove already sampled pixels
                pixels_to_sample_from = pixels_to_sample_from - sampled_pixels
                # Subtract from number of pseudo-points left to sample
                number_of_pseudopoints = number_of_pseudopoints - number_pixels_to_sample_from_bias_grid
                logger.info("Number of pseudo-points left to sample after bias_grid sampling: %s " % number_of_pseudopoints)
            elif number_pixels_to_sample_from_bias_grid > number_of_pseudopoints:
                # hopefully this will rarely happen, as it is very compute-intensive and memory-hungry
                logger.info("More pixels available to sample from bias grid, than necessary. Selecting top %s" % number_of_pseudopoints)
                # make a grid of all pixels from bias_grid that overlap with the pixels_to_sample_from
                pixels_to_sample_from_bias_grid = np.where(pixels_to_sample_from * bias_grid > 0, bias_grid, 0)
                # find the top number_of_pseudopoints (heighest values)
                flat_indices = np.argpartition(pixels_to_sample_from_bias_grid.ravel(), -number_of_pseudopoints - 1)[-number_of_pseudopoints:]
                # some logic to get the indices of the matrix ...
                row_indices, col_indices = np.unravel_index(flat_indices, pixels_to_sample_from_bias_grid.shape)
                sampled_pixels[row_indices, col_indices] = pixels_to_sample_from[row_indices, col_indices]
                del pixels_to_sample_from_bias_grid
                del row_indices, col_indices, flat_indices
                gc.collect()
                return (pixels_to_sample_from, sampled_pixels)
        # These are x/y positions of pixels to sample from. Tuple of arrays.
        (x, y) = np.where(pixels_to_sample_from > 0)
        number_pixels_to_sample_from = x.shape[0]  # == y.shape[0], since every pixel has (x,y) position.
        logger.info("There are %s pixels left to sample from..." % (number_pixels_to_sample_from))

        if number_pixels_to_sample_from == 0:
            logger.error("There are no pixels left to sample from. Perhaps the species raster data")
            logger.error("covers the entire range from which it was intended to sample further.")
            return (pixels_to_sample_from, sampled_pixels)

        if number_pixels_to_sample_from < number_of_pseudopoints:
            logger.warning("There are less pixels to sample from, than the desired number of pseudo-absences")
            logger.warning("Will select all pixels as psedudo-absences.")
            random_indices = np.arange(0, number_pixels_to_sample_from)
        else:
            # now randomly choose <number_of_pseudopoints> indices to fill in with pseudo absences
            # random_indices = np.random.randint(0, number_pixels_to_sample_from, number_of_pseudopoints)
            # Changed the above method with a different one that guarantees unique positions.
            # With on average 6000 (guesstimate) pixels to sample from, the method below
            # is a factor of 50 slower, but guarantees no repetitions,
            # (20 microseconds vs 100 microseconds) compared to the one above.
            random_indices = np.random.choice(number_pixels_to_sample_from,
                                              number_of_pseudopoints,
                                              replace=False)
            logger.info("Filling %s random pixel positions..." % (len(random_indices)))

        # fill in those indices with the pixel values of the environment layer
        for position in random_indices:
            sampled_pixels[x[position]][y[position]] = pixels_to_sample_from[x[position], y[position]]

        logger.info("Sampled %s unique pixels as pseudo-absences." % sampled_pixels.nonzero()[0].shape[0])
        del random_indices
        gc.collect()
        return (pixels_to_sample_from, sampled_pixels)


class VectorEnvironmentalLayer(EnvironmentalLayer):
    """
    VectorEnvironmentalLayer

    A class for encapsulating the vector environmental layer functionality, with operations such as rasterizing.

    :ivar file_path: Full location of the shapefile containing the data for this layer.
    :vartype file_path: string

    :ivar data_full: Data frame containing the full data for the environmental layer geometries.
    :vartype data_full: geopandas.GeoDataFrame

    :ivar raster_file: Full location of the corresponding raster map data for this layer.
    :vartype raster_file: string

    :ivar raster_affine: Affine translation used in the corresponding raster map of this layer.
    :vartype raster_affine: rasterio.transform.Affine

    :ivar raster_reader: file reader for the corresponding rasterized data.
    :vartype raster_reader: rasterio._io.RasterReader

    """
    def __init__(self, source=None, file_path=None, name_layer=None, **kwargs):
        EnvironmentalLayer.__init__(self, source, file_path, name_layer, **kwargs)

    def load_data(self, file_path=None):
        """
        Loads the environmental data from the provided :attr:`file_path` shapefile into a ``geopandas.GeoDataFrame``.
        A GeoDataFrame is a tablular data structure that contains a column called ``geometry`` which contains a GeoSeries of
        `Shapely <http://toblerity.org/shapely/shapely.geometry.html>`_ geometries. all other meta-data column names are
        converted to a lower-case, for consistency.

        :param string file_path: The full path to the shapefile file (including the directory and filename in one string).

        :returns: None

        """
        if file_path:
                self.file_path = file_path

        if not self.file_path:
            raise AttributeError("Please provide a file_path argument to load the data from.")

        logger.info("Loading data from %s " % self.file_path)
        self.data_full = GeoDataFrame.from_file(self.file_path)
        self.data_full.columns = [x.lower() for x in self.data_full.columns]
        logger.info("The shapefile contains data on %d environmental regions." % self.data_full.shape[0])

    def save_data(self, full_name=None, driver='ESRI Shapefile', overwrite=False):
        """
        Saves the current ``geopandas.GeoDataFrame`` data in a shapefile. The data is expected to have a 'geometry'
        as a column, besides other metadata metadata. If the full location and name of the file is not provided,
        then the :attr:`overwrite` should be set to ``True`` to overwrite the existing shapefile from which the
        data was previously loaded.

        :param string file_path: The full path to the targed shapefile file (including the directory and filename in one string).

        :param string driver: The driver to use for storing the geopandas.GeoDataFrame data into a file. Default is "ESRI Shapefile".

        :param bool overwrite: Whether to overwrite the shapefile from which the data was previously loaded, if a new :attr:`file_path` is not supplied.

        :returns: None

        """

        if not (isinstance(self.data_full, GeoSeries) or isinstance(self.data_full, GeoDataFrame)):
            raise AttributeError("The data is not of a Geometry type (GeoSeries or GeoDataFrame).",
                                 "Please geometrize first!")

        if overwrite:
            full_name = self.file_path
        elif not overwrite and full_name is None:
            raise AttributeError("Please provide a shape_file location, or set overwrite=True")

        try:
            self.data_full.to_file(full_name, driver="ESRI Shapefile")
            logger.debug("Saved data: %s " % full_name)
        except AttributeError as e:
            logger.error("Could not save data! %s " % str(e))

    def get_data(self):
        """
        Returns the (pre)loaded species data in a (geo)pandas DataFrame.

        :returns: :attr:`self.data_full`

        :rtype: geopandas.GeoDataFrame or pandas.DataFrame

        """
        return self.data_full

    def set_data(self, data_frame):
        """
        Set the species data to the contents of :attr:`data_frame`. The data passed must be in a
        pandas or geopandas DataFrame.
        **Careful**, it overwrites the existing data!

        :param pandas.DataFrame data_frame: The new data.

        :returns: None

        """

        if not isinstance(self.data_full, GeoDataFrame) or not isinstance(self.data_full, pd.DataFrame):
            raise AttributeError("Data is not in a correct format! Please pass pandas or geopandas DataFrame.")
        else:
            self.data_full = data_frame

    def rasterize(self, raster_file=None,
                  pixel_size=None,
                  all_touched=False,
                  no_data_value=0,
                  default_value=1,
                  crs=None,
                  cropped=False,
                  classifier_column=None,
                  *args, **kwargs):
        """
        Rasterize (burn) the environment rangemaps (geometrical shapes) into pixels (cells), i.e., a 2-dimensional image array
        of type numpy ndarray. Uses the `Rasterio <https://mapbox.github.io/rasterio/_modules/rasterio/features.html>`_ library
        for this purpose. All the shapes from the ``VectorEnvironmentalLayer`` object data are burned in a single *band* of the image.
        Rasterio datasets can generally have one or more bands, or layers. Following the GDAL convention, these are indexed starting with 1.

        :param string raster_file: The full path to the targed GeoTIFF raster file (including the directory and filename in one string).

        :param int pixel_size: The size of the pixel in degrees, i.e., the resolution to use for rasterizing.

        :param bool all_touched: If true, all pixels touched by geometries, will be burned in. If false, only pixels \
        whose center is within the polygon or that are selected by Bresenham's line algorithm, will be burned in.

        :param int no_data_value: Used as value of the pixels which are not burned in. Default is 0.

        :param int default_value: Used as value of the pixels which are burned in. Default is 1.

        :param crs: The Coordinate Reference System to use. Default is "ESPG:4326"

        :param bool cropped: If true, the resulting pixel array (image) is cropped to the region borders, which contain \
        the burned pixels (i.e., an envelope within the range). Otherwise, a "global world map" is used, i.e., the boundaries \
        are set to (-180, -90, 180, 90) for the resulting array.

        :returns: Rasterio RasterReader file object which can be used to read individual bands from the raster file.

        :rtype: rasterio._io.RasterReader

        """
        if not (pixel_size or raster_file):
            raise AttributeError("Please provide pixel_size and a target raster_file.")

        if not hasattr(self, 'data_full'):
            raise AttributeError("You have not loaded the data.")

        if crs is None:
            crs = {'init': "EPSG:4326"}

        # crop to the boundaries of the shape?
        if cropped:
            # cascaded_union_geometry = shapely.ops.cascaded_union(self.data_full.geometry)
            x_min, y_min, x_max, y_max = self.data_full.geometry.total_bounds
        # else global map
        else:
            x_min, y_min, x_max, y_max = -180, -90, 180, 90

        x_res = int((x_max - x_min) / pixel_size)
        y_res = int((y_max - y_min) / pixel_size)
        logger.info("Will rasterize using pixel_size=%s, all_touched=%s, no_data_value=%s, fill_value=%s "
                    % (pixel_size, all_touched, no_data_value, default_value))
        transform = Affine.translation(x_min, y_max) * Affine.scale(pixel_size, -pixel_size)
        if classifier_column:
            logger.info("Will rasterize using classifier: %s." % classifier_column)
            classifier_categories = self.data_full[classifier_column].unique()
            stacked_layers = []
            for category_name in classifier_categories:
                if category_name:
                    logger.info("Rasterizing category %s " % category_name)
                    result = features.rasterize(self.data_full.geometry[self.data_full[classifier_column] == category_name],
                                                transform=transform,
                                                out_shape=(y_res, x_res),
                                                all_touched=all_touched,
                                                fill=no_data_value,
                                                default_value=default_value
                                                )
                    stacked_layers.append(result)

            stacked_layers = np.stack(stacked_layers)

            for i, band in enumerate(stacked_layers, 1):
                with rasterio.open(raster_file, 'w', driver='GTiff', width=x_res, height=y_res,
                                   count=stacked_layers.shape[0],
                                   dtype=np.uint8,
                                   nodata=no_data_value,
                                   transform=transform,
                                   crs=crs) as out:
                    out.write(band.astype(np.uint8), indexes=i)
            result_final = stacked_layers
        else:
            logger.info("Will rasterize everything on a single band.")
            result_final = features.rasterize(self.data_full.geometry,
                                              transform=transform,
                                              out_shape=(y_res, x_res),
                                              all_touched=all_touched,
                                              fill=no_data_value,
                                              default_value=default_value
                                              )

            with rasterio.open(raster_file, 'w', driver='GTiff', width=x_res, height=y_res,
                               count=1,
                               dtype=np.uint8,
                               nodata=no_data_value,
                               transform=transform,
                               crs=crs) as out:
                out.write(result_final.astype(np.uint8), indexes=1)
        out.close()
        logger.info("RASTERIO: Data rasterized into file %s " % raster_file)
        logger.info("RASTERIO: Resolution: x_res={0} y_res={1}".format(x_res, y_res))
        self.raster_file = raster_file
        self.raster_affine = transform
        self.stacked_layers = stacked_layers
        return result_final

    def load_raster_data(self, raster_file=None):
        """
        Loads the raster data from a previously-saved raster file. Provides information about the
        loaded data, and returns a rasterio file reader.

        :param string raster_file: The full path to the targed GeoTIFF raster file (including the directory and filename in one string).

        :returns: Rasterio RasterReader file object which can be used to read individual bands from the raster file.

        :rtype: rasterio._io.RasterReader

        """
        if raster_file:
            self.raster_file = raster_file
        if not self.raster_file:
            raise AttributeError("Please provide a raster_file to read raster data from.")

        src = rasterio.open(self.raster_file)
        logger.info("Loaded raster data from %s " % self.raster_file)
        logger.info("Driver name: %s " % src.driver)
        pp = pprint.PrettyPrinter(depth=5)
        self.metadata = src.meta
        logger.info("Metadata: %s " % pp.pformat(self.metadata))
        logger.info("Resolution: x_res={0} y_res={1}.".format(src.width, src.height))
        logger.info("Bounds: %s " % (src.bounds,))
        logger.info("Coordinate reference system: %s " % src.crs)
        logger.info("Affine transformation: %s " % (src.affine.to_gdal(),))
        logger.info("Number of layers: %s " % src.count)
        logger.info("Dataset loaded. Use .read() or .read_masks() to access the layers.")
        self.raster_affine = src.affine
        self.raster_reader = src
        return self.raster_reader

    def set_classifier(self, classifier_column):
        self.classifier_column = classifier_column

    def get_classifier(self):
        return self.classifier_column

    def set_raster_file(self, raster_file):
        self.raster_file = raster_file

    def get_raster_file(self):
        return self.raster_file

    def set_pixel_size(self, pixel_size):
        self.pixel_size = pixel_size

    def get_pixel_size(self):
        return self.pixel_size


class ClimateLayer(RasterEnvironmentalLayer):
    pass


class DEMLayer(RasterEnvironmentalLayer):
    pass
