"""Script to take the trained everglades model and predict the Palmyra data"""
#srun -p gpu --gpus=1 --mem 20GB --time 5:00:00 --pty -u bash -i
#module load tensorflow/1.14.0
#export PATH=${PATH}:/home/b.weinstein/miniconda3/envs/Zooniverse/bin/
#export PYTHONPATH=${PYTHONPATH}:/home/b.weinstein/miniconda3/envs/Zooniverse/lib/python3.7/site-packages/
#export LD_LIBRARY_PATH=/home/b.weinstein/miniconda3/envs/Zooniverse/lib/:${LD_LIBRARY_PATH}

from deepforest import deepforest
from matplotlib import pyplot as plt
from shapely.geometry import Point, box
import geopandas as gpd
import shapely
import pandas as pd
import rasterio as rio
import numpy as np
import os

import IoU

def shapefile_to_annotations(shapefile, rgb, savedir="."):
    """
    Convert a shapefile of annotations into annotations csv file for DeepForest training and evaluation
    Args:
        shapefile: Path to a shapefile on disk. If a label column is present, it will be used, else all labels are assumed to be "Tree"
        rgb: Path to the RGB image on disk
        savedir: Directory to save csv files
    Returns:
        results: a pandas dataframe
    """
    #Read shapefile
    gdf = gpd.read_file(shapefile)
    gdf = gdf[~gdf.geometry.isnull()]
        
    #raster bounds
    with rio.open(rgb) as src:
        left, bottom, right, top = src.bounds
        resolution = src.res[0]
        
    #define in image coordinates and buffer to create a box
    gdf["geometry"] = gdf.geometry.boundary.centroid
    gdf["geometry"] =[Point(x,y) for x,y in zip(gdf.geometry.x.astype(float), gdf.geometry.y.astype(float))]
    gdf["geometry"] = [box(left, bottom, right, top) for left, bottom, right, top in gdf.geometry.buffer(0.25).bounds.values]
        
    #get coordinates
    df = gdf.geometry.bounds
    df = df.rename(columns={"minx":"xmin","miny":"ymin","maxx":"xmax","maxy":"ymax"})    
    
    #Transform project coordinates to image coordinates
    df["tile_xmin"] = (df.xmin - left)/resolution
    df["tile_xmin"] = df["tile_xmin"].astype(int)
    
    df["tile_xmax"] = (df.xmax - left)/resolution
    df["tile_xmax"] = df["tile_xmax"].astype(int)
    
    #UTM is given from the top, but origin of an image is top left
    
    df["tile_ymax"] = (top - df.ymin)/resolution
    df["tile_ymax"] = df["tile_ymax"].astype(int)
    
    df["tile_ymin"] = (top - df.ymax)/resolution
    df["tile_ymin"] = df["tile_ymin"].astype(int)    
    
    #Add labels is they exist
    if "label" in gdf.columns:
        df["label"] = gdf["label"]
    else:
        df["label"] = "Tree"
    
    #add filename
    df["image_path"] = os.path.basename(rgb)
    
    #select columns
    result = df[["image_path","tile_xmin","tile_ymin","tile_xmax","tile_ymax","label"]]
    result = result.rename(columns={"tile_xmin":"xmin","tile_ymin":"ymin","tile_xmax":"xmax","tile_ymax":"ymax"})
    
    #ensure no zero area polygons due to rounding to pixel size
    result = result[~(result.xmin == result.xmax)]
    result = result[~(result.ymin == result.ymax)]
    
    return result
    
def training(proportion, pretrained=True):
    df = shapefile_to_annotations(shapefile="/orange/ewhite/everglades/Palmyra/TNC_Cooper_annotation_03192021.shp", rgb="/orange/ewhite/everglades/Palmyra/CooperStrawn_53m_tile_clip.tif")
    df.to_csv("Figures/training_annotations.csv",index=False)
    
    df = shapefile_to_annotations(shapefile="TNC_Dudley_annotation", rgb="/orange/ewhite/everglades/Palmyra/palmyra.tif")
    df.sample(proportion=proportion)
    df.to_csv("Figures/testing_annotations.csv",index=False)
    
    src = rio.open("/orange/ewhite/everglades/Palmyra/palymra.tif")
    numpy_image = src.read()
    numpy_image = np.moveaxis(numpy_image,0,2)
    numpy_image = numpy_image[:,:,:3].astype("uint8")
    
    crop_annotations = deepforest.preprocess.split_raster(numpy_image=numpy_image, annotations_file="Figures/testing_annotations.csv", patch_size=2000, base_dir="crops", image_name="palymra.tif")
    crop_annotations.head()
    crop_annotations.to_csv("crops/testing_annotations.csv",index=False, header=False)
    
    train_annotations = deepforest.preprocess.split_raster(numpy_image=numpy_image, annotations_file="Figures/training_annotations.csv", patch_size=2000, base_dir="crops", image_name="CooperStrawn_53m_tile_clip.tif")
    train_annotations.head()
    train_annotations.to_csv("crops/training_annotations.csv",index=False, header=False)
    
    if pretrained:
        model_path = "/orange/ewhite/everglades/Zooniverse/predictions/20210131_015711.h5"
        model = deepforest.deepforest(weights=model_path)
    else:
        model = deepforest.deepforest()
    
    try:
        os.mkdir("/orange/ewhite/everglades/Palmyra/{}/".format(proportion))
    except:
        pass
    
    model.config["save_path"] = "/orange/ewhite/everglades/Palmyra/"
    model.train(annotations="crops/training_annotations.csv")
    model.evaluate_generator(annotations="crops/dudley_annotations.csv", color_annotation=(0,255,0),color_detection=(255,255,0))
    
    #Evaluate against model
    boxes = model.predict_tile(numpy_image=numpy_image, return_plot=False, patch_size=2000)
    bounds = src.bounds
    pixelSizeX, pixelSizeY  = src.res
    
    #subtract origin. Recall that numpy origin is top left! Not bottom left.
    boxes["xmin"] = (boxes["xmin"] *pixelSizeX) + bounds.left
    boxes["xmax"] = (boxes["xmax"] * pixelSizeX) + bounds.left
    boxes["ymin"] = bounds.top - (boxes["ymin"] * pixelSizeY) 
    boxes["ymax"] = bounds.top - (boxes["ymax"] * pixelSizeY)
    
    # combine column to a shapely Box() object, save shapefile
    boxes['geometry'] = boxes.apply(lambda x: shapely.geometry.box(x.xmin,x.ymin,x.xmax,x.ymax), axis=1)
    boxes = gpd.GeoDataFrame(boxes, geometry='geometry')
    
    boxes.crs = src.crs.to_wkt()
    boxes.to_file("Figures/predictions.shp")
    
    #define in image coordinates and buffer to create a box
    gdf = gpd.read_file("/orange/ewhite/everglades/Palmyra/TNC_Dudley_annotation.shp")
    gdf = gdf[~gdf.geometry.isnull()]
    gdf["geometry"] = gdf.geometry.boundary.centroid
    gdf["geometry"] =[Point(x,y) for x,y in zip(gdf.geometry.x.astype(float), gdf.geometry.y.astype(float))]
    gdf["geometry"] = [box(left, bottom, right, top) for left, bottom, right, top in gdf.geometry.buffer(0.25).bounds.values]
    
    results = IoU.compute_IoU(gdf, boxes)
    results["match"] = results.score > 0.4
    true_positive = sum(results["match"] == True)
    recall = true_positive / results.shape[0]
    precision = true_positive / boxes.shape[0]
    
    print("Recall is {}".format(recall))
    print("Precision is {}".format(precision))
    
    return precision, recall

proportion = []
recall = []
precision = []

for x in np.arange(0,120,20)/100:
    p, r = training(proportion=x)
    precision.append(p)
    recall.append(r)
    proportion.append(x)

results = pd.DataFrame({"precision":precision,"recall": recall,"proportion":proportion})
results.to_csv("Figures/results.csv") 