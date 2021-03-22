#DeepForest bird detection from extracted Zooniverse predictions
import comet_ml
from pytorch_lightning.loggers import CometLogger
from deepforest.callbacks import images_callback
from deepforest import main
import pandas as pd
import os
import numpy as np
from datetime import datetime

def is_empty(precision_curve, threshold):
    precision_curve.score = precision_curve.score.astype(float)
    precision_curve = precision_curve[precision_curve.score > threshold]
    
    return precision_curve.empty

def empty_image(precision_curve, threshold):
    empty_true_positives = 0
    empty_false_negatives = 0
    for name, group in precision_curve.groupby('image'): 
        if is_empty(group, threshold):
            empty_true_positives +=1
        else:
            empty_false_negatives+=1
    empty_recall = empty_true_positives/float(empty_true_positives + empty_false_negatives)
    
    return empty_recall

def plot_recall_curve(precision_curve, invert=False):
    """Plot recall at fixed interval 0:1"""
    recalls = {}
    for i in np.linspace(0,1,11):
        recalls[i] = empty_image(precision_curve=precision_curve, threshold=i)
    
    recalls = pd.DataFrame(list(recalls.items()), columns=["threshold","recall"])
    
    if invert:
        recalls["recall"] = 1 - recalls["recall"].astype(float)
    
    ax1 = recalls.plot.scatter("threshold","recall")
    
    return ax1
    
def predict_empty_frames(model, empty_images, comet_logger, invert=False):
    """Optionally read a set of empty frames and predict
        Args:
            invert: whether the recall should be relative to empty images (default) or non-empty images (1-value)"""
    
    #Create PR curve
    precision_curve = [ ]
    for path in empty_images:
        boxes = model.predict_image(path, return_plot=False)
        boxes["image"] = path
        precision_curve.append(boxes)
    
    precision_curve = pd.concat(precision_curve)
    recall_plot = plot_recall_curve(precision_curve, invert=invert)
    value = empty_image(precision_curve, threshold=0.4)
    
    if invert:
        value = 1 - value
        metric_name = "BirdRecall_at_0.4"
        recall_plot.set_title("Atleast One Bird Recall")
    else:
        metric_name = "EmptyRecall_at_0.4"
        recall_plot.set_title("Empty Recall")        
        
    comet_logger.experiment.log_metric(metric_name,value)
    comet_logger.experiment.log_figure(recall_plot)   
    
def train_model(train_path, test_path, empty_images_path=None, save_dir="."):
    """Train a DeepForest model"""
    
    comet_logger = CometLogger(api_key="ypQZhYfs3nSyKzOfz13iuJpj2",
                                  project_name="everglades-species", workspace="bw4sz")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_savedir = "{}/{}".format(save_dir,timestamp)    
    
    comet_logger.experiment.log_parameter("timestamp",timestamp)
    
    #Log the number of training and test
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)

    #Set config and train'    
    label_dict = {key:value for value, key in enumerate(train.label.unique())}
    model = main.deepforest(num_classes=len(train.label.unique()),label_dict=label_dict)
    
    model.config["train"]["csv_file"] = train_path
    model.config["train"]["root_dir"] = os.path.dirname(train_path)
    
    #Set config and train
    model.config["validation"]["csv_file"] = test_path
    model.config["validation"]["root_dir"] = os.path.dirname(test_path)
    
    if comet_logger is not None:
        comet_logger.experiment.log_parameters(model.config)
        comet_logger.experiment.log_parameter("Training_Annotations",train.shape[0])    
        comet_logger.experiment.log_parameter("Testing_Annotations",test.shape[0])
        
    im_callback = images_callback(csv_file=model.config["validation"]["csv_file"], root_dir=model.config["validation"]["root_dir"], savedir=model_savedir, n=8)    
    model.create_trainer(callbacks=[im_callback], logger=comet_logger)
    model.trainer.fit(model)
    
    #Manually convert model
    results = model.evaluate(test_path, root_dir = os.path.dirname(test_path))
    
    if comet_logger is not None:
        comet_logger.experiment.log_asset(results["result"])
        comet_logger.experiment.log_asset(results["class_recall"])
        comet_logger.experiment.log_metric("Average Class Recall",results["class_recall"].recall.mean())
        comet_logger.experiment.log_parameter("saved_checkpoint","{}/species_model.pl".format(model_savedir))
        
        ypred = results["results"].predicted_label
        ytrue = results["results"].true_label
        comet_logger.experiment.log_confusion_matrix(ytrue,ypred, list(model.label_dict.keys()))
        
    #Create a positive bird recall curve
    test_frame_df = pd.read_csv(test_path, names=["image_name","xmin","ymin","xmax","ymax","label"])
    dirname = os.path.dirname(test_path)
    test_frame_df["image_path"] = test_frame_df["image_name"].apply(lambda x: os.path.join(dirname,x))
    empty_images = test_frame_df.image_path.unique()    
    predict_empty_frames(model, empty_images, comet_logger.experiment, invert=True)
    
    #Test on empy frames
    if empty_images_path:
        empty_frame_df = pd.read_csv(empty_images_path)
        empty_images = empty_frame_df.image_path.unique()    
        predict_empty_frames(model, empty_images, comet_logger.experiment)
    
    #save model
    model.save_checkpoint("{}/species_model.pl".format(model_savedir))
    
    return model

if __name__ == "__main__":
    train_model(train_path="/orange/ewhite/everglades/Zooniverse/parsed_images/train.csv", test_path="/orange/ewhite/everglades/Zooniverse/parsed_images/test.csv", save_dir="/orange/ewhite/everglades/Zooniverse/")