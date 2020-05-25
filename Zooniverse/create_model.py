#DeepForest bird detection from extracted Zooniverse predictions
import comet_ml
from deepforest import deepforest
import geopandas as gp
from shapely.geometry import Point, box
import pandas as pd
import rasterio
import os
import numpy as np
import random
import glob
from datetime import datetime

#Define shapefile utility
def shapefile_to_annotations(shapefile, rgb_path, savedir="."):
    """
    Convert a shapefile of annotations into annotations csv file for DeepForest training and evaluation
    Args:
        shapefile: Path to a shapefile on disk. If a label column is present, it will be used, else all labels are assumed to be "Tree"
        rgb_path: Path to the RGB image on disk
        savedir: Directory to save csv files
    Returns:
        None: a csv file is written
    """
    #Read shapefile
    gdf = gp.read_file(shapefile)
    
    #define in image coordinates and buffer to create a box
    gdf["geometry"] =[Point(x,y) for x,y in zip(gdf.x.astype(float), gdf.y.astype(float))]
    gdf["geometry"] = [box(int(left), int(bottom), int(right), int(top)) for left, bottom, right, top in gdf.geometry.buffer(25).bounds.values]
        
    #extent bounds
    df = gdf.bounds
    
    #Assert size mantained
    assert df.shape[0] == gdf.shape[0]
    
    df = df.rename(columns={"minx":"xmin","miny":"ymin","maxx":"xmax","maxy":"ymax"})
    
    #cut off on borders
    with rasterio.open(rgb_path) as src:
        height, width = src.shape
        
    df.ymax[df.ymax > height] = height
    df.xmax[df.xmax > width] = width
    df.ymin[df.ymin < 0] = 0
    df.xmin[df.xmin < 0] = 0
    
    #add filename and bird labels
    df["image_path"] = os.path.basename(rgb_path)
    df["label"] = "Bird"
    
    #enforce pixel rounding
    df.xmin = df.xmin.astype(int)
    df.ymin = df.ymin.astype(int)
    df.xmax = df.xmax.astype(int)
    df.ymax = df.ymax.astype(int)
    
    #select columns
    result = df[["image_path","xmin","ymin","xmax","ymax","label"]]
    
    #Drop any rounding errors duplicated
    result = result.drop_duplicates()
    
    return result

def find_rgb_path(shp_path, image_dir):
    basename = os.path.splitext(os.path.basename(shp_path))[0]
    rgb_path = "{}/{}.png".format(image_dir,basename)
    return rgb_path
    
def format_shapefiles(shp_dir,image_dir=None):
    """
    Format the shapefiles from extract.py into a list of annotations compliant with DeepForest -> [image_name, xmin,ymin,xmax,ymax,label]
    shp_dir: directory of shapefiles
    image_dir: directory of images. If not specified, set as shp_dir
    """
    if not image_dir:
        image_dir = shp_dir
        
    shapefiles = glob.glob(os.path.join(shp_dir,"*.shp"))
    
    #Assert all are unique
    assert len(shapefiles) == len(np.unique(shapefiles))
    
    annotations = [ ]
    for shapefile in shapefiles:
        rgb_path = find_rgb_path(shapefile, image_dir)
        result = shapefile_to_annotations(shapefile, rgb_path)
        annotations.append(result)
    annotations = pd.concat(annotations)
    
    return annotations

def split_test_train(annotations):
    """Split annotation in train and test by image"""
    image_names = annotations.image_path.unique()
    train_names = np.random.choice(image_names, int(len(image_names) * 0.9))
    train = annotations[annotations.image_path.isin(train_names)]
    test = annotations[~(annotations.image_path.isin(train_names))]
    
    return train, test

def predict_empty_frames(model, empty_images_path, comet_experiment):
    """Optionally read a set of empty frames and predict"""
    empty_frame_df = pd.read_csv(empty_images_path)
    empty_images = empty_frame_df.image_path.unique()
    
    empty_true_positives = 0
    empty_false_negatives = 0
    for path in empty_images:
        boxes = model.predict_image(path, return_plot=False)
        if boxes.empty:
            empty_true_positives +=1
        else:
            empty_false_negatives +=1
    
    empty_recall = empty_true_positives/float(empty_true_positives + empty_false_negatives)
    comet_experiment.log_metric("empty_recall", empty_recall)
    print("Empty frame recall is {}".format(empty_recall))
    
def train_model(train_path, test_path, empty_images_path=None, save_dir="."):
    """Train a DeepForest model"""
    model = deepforest.deepforest()
    model.use_release()
    comet_experiment = comet_ml.Experiment(api_key="ypQZhYfs3nSyKzOfz13iuJpj2",
                                  project_name="everglades", workspace="bw4sz")
    comet_experiment.log_parameters(model.config)
    
    #Log the number of training and test
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)
    comet_experiment.log_parameter("Training_Annotations",train.shape[0])    
    comet_experiment.log_parameter("Testing_Annotations",test.shape[0])
    
    #Set config and train
    model.config["validation_annotations"] = test_path
    model.config["save_path"] = save_dir
    model.train(train_path, comet_experiment=comet_experiment)
    
    #Test on empy frames
    if empty_images_path:
        predict_empty_frames(model, empty_images_path, comet_experiment)
    
    return model
    
def run(shp_dir, empty_frames_path=None, save_dir="."):
    """Parse annotations, create a test split and train a model"""
    annotations = format_shapefiles(shp_dir)
    random.seed(2)
    
    #Split train and test
    train, test = split_test_train(annotations)
    
    #write paths to headerless files alongside data
    train_path = "{}/train.csv".format(shp_dir)
    test_path = "{}/test.csv".format(shp_dir)
    
    train.to_csv(train_path, index=False,header=False)
    test.to_csv(test_path, index=False,header=False)
    
    model = train_model(train_path, test_path, empty_frames_path, save_dir)
    
    #Save
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model.prediction_model.save("{}/{}.h5".format(save_dir,timestamp))
    
if __name__ == "__main__":
    run(
        shp_dir="/orange/ewhite/everglades/Zooniverse/parsed_images/",
        empty_frames_path="/orange/ewhite/everglades/Zooniverse/parsed_images/empty_frames.csv",
        save_dir="/orange/ewhite/everglades/Zooniverse/predictions/"
    )
    