#Transform augmentations
import albumentations as A
from albumentations import functional as F
from albumentations.augmentations.bbox_utils import union_of_bboxes
import random
import numpy as np
import cv2

## general style
#def get_transform(augment):
    #"""Albumentations transformation of bounding boxs"""
    #if augment:
        #transform = A.Compose([
            #A.HorizontalFlip(p=0.5),
            #ToTensorV2()
        #], bbox_params=A.BboxParams(format='pascal_voc',label_fields=["category_ids"]))
        
    #else:
        #transform = A.Compose([ToTensorV2()])
        
    #return transform

#TODO Make the crop size probabilistic. 

def get_transform(augment):
    """Albumentations transformation of bounding boxs"""
    if augment:
        transform = A.Compose([
            A.GaussianBlur(),
            A.Flip(p=0.5),
            A.RandomBrightnessContrast(),
            A.pytorch.ToTensorV2(),
        ], bbox_params=A.BboxParams(format='pascal_voc',label_fields=["category_ids"]))
        
    else:
        transform = A.Compose([A.pytorch.ToTensorV2()])
        
    return transform

class ZoomSafe(A.DualTransform):
    """Crop a random part of the input and rescale it to some size without loss of bboxes.
    Args:
        height (int): height after crop and resize.
        width (int): width after crop and resize.
        erosion_rate (float): erosion rate applied on input image height before crop.
        interpolation (OpenCV flag): flag that is used to specify the interpolation algorithm. Should be one of:
            cv2.INTER_NEAREST, cv2.INTER_LINEAR, cv2.INTER_CUBIC, cv2.INTER_AREA, cv2.INTER_LANCZOS4.
            Default: cv2.INTER_LINEAR.
        p (float): probability of applying the transform. Default: 1.
    Targets:
        image, mask, bboxes
    Image types:
        uint8, float32
    """

    def __init__(self, height, width, erosion_rate=0.0, interpolation=cv2.INTER_LINEAR, always_apply=False, p=1.0):
        super(ZoomSafe, self).__init__(always_apply, p)
        self.height = height
        self.width = width
        self.interpolation = interpolation
        self.erosion_rate = erosion_rate

    def apply(self, img, crop_height=0, crop_width=0, h_start=0, w_start=0, interpolation=cv2.INTER_LINEAR, **params):
        crop = F.random_crop(img, crop_height, crop_width, h_start, w_start)
        return F.resize(crop, self.height, self.width, interpolation)

    def get_params_dependent_on_targets(self, params):
        img_h, img_w = params["image"].shape[:2]
        if len(params["bboxes"]) == 0:  # less likely, this class is for use with bboxes.
            erosive_h = int(img_h * (1.0 - self.erosion_rate))
            crop_height = img_h if erosive_h >= img_h else random.randint(erosive_h, img_h)
            return {
                "h_start": random.random(),
                "w_start": random.random(),
                "crop_height": crop_height,
                "crop_width": int(crop_height * img_w / img_h),
            }
        # get union of selected bboxes
        index = np.random.choice(params["bboxes"].shape[0], 1, replace=False)
        selected_boxes = params["bboxes"][index,:]
        x, y, x2, y2 = union_of_bboxes(
            width=img_w, height=img_h, bboxes=selected_boxes, erosion_rate=self.erosion_rate
        )
        # Create a box around the x, y
        x_box_width = x2-x
        side_width = img_w - x2
        w_lower = np.max(x - (self.width - x_box_width), 0)
        w_upper = x - (self.width - x_box_width - side_width)
        w_start = np.random.randint(w_lower,w_upper)
        
        y_box_height = y2-y
        side_height = img_h - y2
        h_lower = np.max(y - (self.height - y_box_height), 0)
        h_upper = y - (self.height - y_box_height - side_height)
        h_start = np.random.randint(h_lower,h_upper)
        
        return {"h_start": h_start, "w_start": w_start, "crop_height": self.height, "crop_width": self.width}

    def apply_to_bbox(self, bbox, crop_height=0, crop_width=0, h_start=0, w_start=0, rows=0, cols=0, **params):
        return F.bbox_random_crop(bbox, crop_height, crop_width, h_start, w_start, rows, cols)

    @property
    def targets_as_params(self):
        return ["image", "bboxes"]

    def get_transform_init_args_names(self):
        return ("height", "width", "erosion_rate", "interpolation")