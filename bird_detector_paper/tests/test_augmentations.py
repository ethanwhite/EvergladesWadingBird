#Test Augmentations
import augmentation
import os
from deepforest import main
from deepforest import get_data

def test_get_transform():
    csv_file = get_data("OSBS_029.csv")    
    m = main.deepforest(num_classes=1, label_dict={"Tree":0},transforms=augmentation.get_transform)
    m.config["workers"] = 0
    ds = m.load_dataset(csv_file=csv_file, root_dir=os.path.dirname(csv_file), augment=True)
    
    step = next(iter(ds))
    len(step) == 3
    assert step[1][0].shape == (300,300, 3)
    
