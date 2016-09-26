import logging
# import timeit
import pandas as pd
import numpy as np
# from iSDM.environment import RasterEnvironmentalLayer
from iSDM.environment import RasterEnvironmentalLayer
# from iSDM.environment import Source
# from iSDM.environment import ClimateLayer
from iSDM.species import IUCNSpecies, GBIFSpecies
from iSDM.model import Model
# from rasterio.transform import Affine

# from iSDM.model import Algorithm
import os
import argparse
import errno
# import rasterio
import gc
import sys

parser = argparse.ArgumentParser()
parser.add_argument('-r', '--realms-location', default=os.path.join(os.getcwd(), "data", "freshwater_ecoregions"), help='The full path to the folder where the realms/ecoregions raster file is located.')
parser.add_argument('-l', '--habitat-location', default=os.path.join(os.getcwd(), "data", "GLWD", "downscaled"), help="The folder where the suitable-habitat raster file is.")
parser.add_argument('-s', '--species-location', default=os.path.join(os.getcwd(), "data", "fish"), help="The folder where the IUCN species shapefiles are located.")
parser.add_argument('-g', '--gbif-location', default=os.path.join(os.getcwd(), "data", "fish", "selection", "gbif"), help="The folder where the GBIF species observations are located.")
parser.add_argument('-o', '--output-location', default=os.path.join(os.getcwd(), "data", "fish"), help="Output location (folder) for storing the output of the processing.")
parser.add_argument('-p', '--pixel-size', type=float, default=0.0083333333, help="Resolution (in target georeferenced units, i.e., the pixel size). Assumed to be square, so only one value needed.")
parser.add_argument('--reprocess', action='store_true', help="Reprocess the data, using the already-rasterized individual species rangemaps. Assumes these files are all available.")
parser.set_defaults(reprocess=False)
args = parser.parse_args()

# 0. logging
try:
    os.makedirs(args.output_location)
except OSError as e:
    if e.errno != errno.EEXIST:
        raise

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
fh = logging.FileHandler(os.path.join(args.output_location, "step2_overlay.log"))
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)

# 1. Use freshwater ecoregions as the "base" matrix (for computing global coordinates, oceans not needed here.)
pixel_size = args.pixel_size
x_min, y_min, x_max, y_max = -180, -90, 180, 90
x_res = int((x_max - x_min) / pixel_size)
y_res = int((y_max - y_min) / pixel_size)

freshwater_layer = RasterEnvironmentalLayer(file_path=os.path.join(args.realms_location, "freshwater_ecoregions.tif"), name_layer="Freshwater_Ecoregion")
# freshwater_layer = RasterEnvironmentalLayer(file_path=os.path.join(args.realms_location, "freshwater_ecoregions_lowres.tif"), name_layer="Freshwater_Ecoregion")
logger.info("Opening layer: %s " % freshwater_layer.name_layer)
freshwater_reader = freshwater_layer.load_data()
freshwater_data = freshwater_reader.read(1)
freshwater_data[freshwater_data == freshwater_reader.nodata] = 0  # cutoff any nodata values (like here 255)

# logger.info("%s data has %s data pixels. " % (freshwater_layer.name_layer, np.count_nonzero(freshwater_data)))
# if freshwater_data.shape != (y_res, x_res):
#     logger.error("The layer is not at the proper resolution! Layer shape:%s " % (freshwater_data.shape, ))
#     sys.exit("The layer is not at the proper resolution! Layer shape:%s " % (freshwater_data.shape, ))

# logger.info("Using %s as a base frame." % freshwater_layer.name_layer)
# habitat_model = Model(pixel_size=pixel_size, raster_data=freshwater_data)  # use freshwater ecoregions as a "base". optionally, all pixels will be taken if no raster_data provided
# # base_dataframe = habitat_model.get_base_dataframe()
# # Load suitable habitat layer
# habitat_model.add_environmental_layer(freshwater_layer)  # not needed?
# glwd_layer = RasterEnvironmentalLayer(file_path=os.path.join(args.habitat_location, "downscaled_bilinear_again_lowres.tif"), name_layer="GLWD")
# logger.info("Adding layer: %s " % glwd_layer.name_layer)
# glwd_reader = glwd_layer.load_data()
# glwd_data = glwd_reader.read(1)
# # hmmm this below is useless, as the data is read from scratch again when adding the layer :-/
# # better prepare the layer in the expected form
# glwd_data[glwd_data != glwd_reader.nodata] = 1  # unify all pixel values (now ranging [1,..,12])
# glwd_data[glwd_data == glwd_reader.nodata] = 0  # any nodata values (like here 255)
# logger.info("%s data has %s data pixels. " % (glwd_layer.name_layer, np.count_nonzero(glwd_data)))
# if glwd_data.shape != (y_res, x_res):
#     logger.error("The layer is not at the proper resolution! Layer shape:%s " % (glwd_data.shape, ))
#     sys.exit("The layer is not at the proper resolution! Layer shape:%s " % (glwd_data.shape, ))

# habitat_model.add_environmental_layer(glwd_layer)
# logger.info("Saving base_merged dataframe to csv")
# base_merged = habitat_model.get_base_dataframe()
# logger.info("Base_merged has shape %s " % (base_merged.shape, ))
# base_merged.to_csv(os.path.join(args.output_location, "base_merged.csv"))
# del base_merged
gc.collect()

logger.info("STEP 3: LOADING all species rangemaps.")
species_iucn = IUCNSpecies(name_species='All')
species_iucn.load_shapefile(args.species_location)   # warning, all species data will be loaded, may take a while!!
# 3.1 Get the list of non-extinct binomials, for looping through individual species
species_data = species_iucn.get_data()
species_iucn.drop_extinct_species()
non_extinct_species = species_iucn.get_data()
non_extinct_binomials = non_extinct_species.binomial.unique().tolist()

try:
    os.makedirs(os.path.join(args.output_location, "rasterized"))
except OSError as e:
    if e.errno != errno.EEXIST:
        raise
try:
    os.makedirs(os.path.join(args.output_location, "csv"))
except OSError as e:
    if e.errno != errno.EEXIST:
        raise


list_gbif_files = [filename for filename in os.listdir(args.gbif_location)]
species_gbif = GBIFSpecies(name_species='All')   # create only one object and update it in the loop

# LOOP THROUGH IUCN SPECIES
logger.info(">>>>>>>>>>>>>>>>>Looping through species!<<<<<<<<<<<<<<<<")
for idx, name_species in enumerate(non_extinct_binomials):
    species_iucn.set_data(species_data[species_data.binomial == name_species])
    species_iucn.name_species = name_species
    logger.info("ID=%s Processing species: %s " % (idx, name_species))

    # RASTERIZE SPECIES GBIF POINT-RECORDS
    species_gbif.name_species = species_iucn.name_species
    logger.info("%s Locating GBIF occurrences file for species %s " % (idx, name_species))
    prefixed = [filename for filename in list_gbif_files if filename.startswith(species_gbif.name_species)]
    if len(prefixed) != 1:
        logger.error("%s Could NOT find the appropriate GBIF file, OR found more than one matching the name for species: %s." % (idx, name_species))
        continue
    logger.info("%s Located GBIF file for species %s . Loading data." % (idx, name_species))
    # load the corresponding GBIF file for species
    species_gbif.load_data(os.path.join(args.gbif_location, prefixed[0]))
    # filter out only GBIF records according to criteria (with lat/long, not older than 1990, AND tyoe of observation is HUMAN_OBSERVATION/OBSERVATION/MACHINE_OBSERVATION)
    gbif_df = species_gbif.get_data()
    logger.info("%s There are %s (unfiltered!) observations for species %s " % (idx, gbif_df.shape[0], name_species))
    logger.info("%s Filtering useful GBIF records according to predefined criteria for species %s ." % (idx, name_species))
    if not ("decimallatitude" in gbif_df.columns.tolist() and "decimallongitude" in gbif_df.columns.tolist()):
        logger.error("%s Species %s GBIF data does NOT have latitude/longitude information. Probably no observations at all! " % (idx, name_species))
        continue
    # the criteria (can be adjusted)
    # TODO: AttributeError: 'DataFrame' object has no attribute 'year'
    gbif_df = gbif_df[gbif_df.decimallatitude.notnull() &
                      gbif_df.decimallongitude.notnull() &
                      ((gbif_df.year > 1990) | (gbif_df.eventdate > "1990")) &  # TODO: what about dataframes without "year" or "eventdate" attributes
                      ((gbif_df.basisofrecord == 'OBSERVATION') |
                      (gbif_df.basisofrecord == 'HUMAN_OBSERVATION') |
                      (gbif_df.basisofrecord == 'MACHINE_OBSERVATION'))]
    logger.info("%s There are %s observations for species %s " % (idx, gbif_df.shape[0], name_species))
    if gbif_df.shape[0] == 0:
        logger.error("%s After filtering out, no good GBIF records for species %s !" % (idx, name_species))
        continue
    species_gbif.set_data(gbif_df)
    gc.collect()

    # overlay GBIF records with IUCN rangemap
    logger.info("%s Overlaying GBIF records to the IUCN rangemap area for species %s." % (idx, name_species))
    species_gbif.overlay(species_iucn)
    if species_gbif.get_data().shape[0] == 0:
        logger.error("%s After overlaying with IUCN rangemap, no GBIF records left for species %s !" % (idx, name_species))
        continue
    logger.info("%s After overlaying with IUCN rangemap, there are %s GBIF records left for species %s." % (idx, species_gbif.get_data().shape[0], name_species))
    logger.info("%s Rasterizing remaining GBIF species %s " % (idx, name_species))
    # gbif_rasterized = species_gbif.rasterize(raster_file=os.path.join(args.output_location, "rasterized", name_species + "_gbif.tif"), pixel_size=pixel_size)
    gbif_rasterized = species_gbif.rasterize(pixel_size=pixel_size)
    if not (isinstance(gbif_rasterized, np.ndarray)) or not (set(np.unique(gbif_rasterized)) == set({0, 1})):
        logger.warning("%s Rasterizing very small GBIF data, will use all_touched=True to avoid blank raster for species %s " % (idx, name_species))
        # gbif_rasterized = species_gbif.rasterize(raster_file=os.path.join(args.output_location, "rasterized", name_species + "_gbif.tif"), pixel_size=pixel_size, all_touched=True)
        gbif_rasterized = species_gbif.rasterize(pixel_size=pixel_size, all_touched=True)
        if not (isinstance(gbif_rasterized, np.ndarray)) or not (set(np.unique(gbif_rasterized)) == set({0, 1})):
            logger.error("%s Rsterizing GBIF records did not succeed for species %s , (raster is empty)    " % (idx, name_species))
            continue
    logger.info("%s Finished rasterizing GBIF records for species: %s " % (idx, name_species))
    logger.info("%s Pixel-to-world coordinates transformation of filtered GBIF presences for species: %s " % (idx, name_species))
    filtered_gbif_coordinates = species_gbif.pixel_to_world_coordinates(raster_data=gbif_rasterized)
    logger.info("%s Finished pixel-to-world coordinates transformation of filtered GBIF presences for species : %s " % (idx, name_species))
    logger.info("%s Constructing a data frame for filtered GBIF presences." % idx)
    filtered_gbif_dataframe = pd.DataFrame(columns=['decimallatitude', 'decimallongitude'])
    filtered_gbif_dataframe['decimallatitude'] = np.array(filtered_gbif_coordinates[0])
    filtered_gbif_dataframe['decimallongitude'] = np.array(filtered_gbif_coordinates[1])
    filtered_gbif_dataframe[species_iucn.name_species] = 1   # fill definitive presences with 1's
    filtered_gbif_dataframe.set_index(['decimallatitude', 'decimallongitude'], inplace=True, drop=True)
    gc.collect()

    logger.info("%s Finished constructing a data frame for filtered GBIF presences for species %s." % (idx, name_species))
    logger.info("%s Shape of filtered GBIF presences dataframe: %s " % (idx, filtered_gbif_dataframe.shape,))
    logger.info("%s Selecting pseudo-absences for species: %s " % (idx, name_species))
    selected_layers, pseudo_absences = freshwater_layer.sample_pseudo_absences(species_raster_data=gbif_rasterized,
                                                                               number_of_pseudopoints=1000)
    logger.info("%s Finished selecting pseudo-absences for species: %s " % (idx, name_species))
    if pseudo_absences is not None:
        logger.info("%s Pixel-to-world coordinates transformation of pseudo-absences for species: %s " % (idx, name_species))
        pseudo_absence_coordinates = species_gbif.pixel_to_world_coordinates(raster_data=pseudo_absences)
        logger.info("%s Finished pixel-to-world coordinates transformation of pseudo-absences for species: %s " % (idx, name_species))
        logger.info("%s Constructing a data frame for pseudo-absences" % idx)
        pseudo_absences_dataframe = pd.DataFrame(columns=['decimallatitude', 'decimallongitude'])
        pseudo_absences_dataframe['decimallatitude'] = np.array(pseudo_absence_coordinates[0])
        pseudo_absences_dataframe['decimallongitude'] = np.array(pseudo_absence_coordinates[1])
        pseudo_absences_dataframe[species_iucn.name_species] = 0   # fill pseudo-absences with 0
        pseudo_absences_dataframe.set_index(['decimallatitude', 'decimallongitude'], inplace=True, drop=True)
        logger.info("%s Finished constructing a data frame for pseudo-absences." % idx)
        logger.info("%s Shape of pseudo-absences dataframe: %s " % (idx, pseudo_absences_dataframe.shape,))
        # merge with presences
        logger.info("%s Merging presences and pseudo-absences..." % idx)
        merged = pd.merge(filtered_gbif_dataframe, pseudo_absences_dataframe, how='outer', left_index=True, right_index=True, on=species_iucn.name_species)
        del pseudo_absences_dataframe
    else:
        logger.warning("%s No pseudo absences sampled for species %s " % (idx, name_species))
        merged = filtered_gbif_dataframe
    logger.info("%s Shape of merged dataframe: %s " % (idx, merged.shape,))
    merged.sortlevel(level=[0, 1], axis=0, ascending=[False, True], inplace=True)
    logger.info("%s Finished processing species: %s " % (idx, name_species))
    logger.info("%s Serializing to storage." % idx)
    merged.to_csv(open(os.path.join(args.output_location, "csv", name_species + ".csv"), "w"))
    logger.info("%s Finished serializing to storage." % idx)
    del filtered_gbif_dataframe
    del merged
    # del merged
logger.info("DONE!")
