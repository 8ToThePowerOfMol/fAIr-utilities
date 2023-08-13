# Standard library imports
import os
import time
from glob import glob
from pathlib import Path

# Third party imports
import numpy as np
import torch
from tensorflow import keras
from ultralytics import YOLO, FastSAM

from ..georeferencing import georeference
from ..utils import remove_files
from .utils import open_images, save_mask, initialize_model

BATCH_SIZE = 8
IMAGE_SIZE = 256
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"


def predict(
    checkpoint_path: str, input_path: str, prediction_path: str, confidence: float = 0.5
) -> None:
    """Predict building footprints for aerial images given a model checkpoint.

    This function reads the model weights from the checkpoint path and outputs
    predictions in GeoTIF format. The input images have to be in PNG format.

    The predicted masks will be georeferenced with EPSG:3857 as CRS.

    Args:
        checkpoint_path: Path where the weights of the model can be found.
        input_path: Path of the directory where the images are stored.
        prediction_path: Path of the directory where the predicted images will go.
        confidence: Threshold probability for filtering out low-confidence predictions.

    Example::

        predict(
            "model_1_checkpt.tf",
            "data/inputs_v2/4",
            "data/predictions/4"
        )
    """
    start = time.time()
    print(f"Using : {checkpoint_path}")
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = initialize_model(checkpoint_path, device=device)
    print(f"It took {round(time.time()-start)} sec to load model")
    start = time.time()

    os.makedirs(prediction_path, exist_ok=True)
    image_paths = glob(f"{input_path}/*.png")

    if isinstance(model, keras.Model):
        for i in range((len(image_paths) + BATCH_SIZE - 1) // BATCH_SIZE):
            image_batch = image_paths[BATCH_SIZE * i : BATCH_SIZE * (i + 1)]
            images = open_images(image_batch)
            images = images.reshape(-1, IMAGE_SIZE, IMAGE_SIZE, 3)

            preds = model.predict(images)
            preds = np.argmax(preds, axis=-1)
            preds = np.expand_dims(preds, axis=-1)
            preds = np.where(
                preds > confidence, 1, 0
            )  # Filter out low confidence predictions

            for idx, path in enumerate(image_batch):
                save_mask(
                    preds[idx],
                    str(f"{prediction_path}/{Path(path).stem}.png"),
                )
    elif isinstance(model, YOLO):
        raise NotImplementedError
    elif isinstance(model, FastSAM):
        results = model(image_paths, stream=True, imgsz=IMAGE_SIZE,
                        prompts=["building" for _ in range(len(image_paths))])
        for i, r in enumerate(results):
            preds = r.masks.data.max(dim=0)[0]
            preds = torch.where(preds > confidence, torch.tensor(1), torch.tensor(0))
            preds = preds.detach().cpu().numpy()
            save_mask(preds, str(f"{prediction_path}/{Path(image_paths[i]).stem}.png"))
    else:
        raise RuntimeError("Loaded model is not supported")

    print(
        f"It took {round(time.time()-start)} sec to predict with {confidence} Confidence Threshold"
    )
    if isinstance(model, keras.Model):
        keras.backend.clear_session()
    del model
    start = time.time()

    georeference(prediction_path, prediction_path, is_mask=True)
    print(f"It took {round(time.time()-start)} sec to georeference")

    remove_files(f"{prediction_path}/*.xml")
    remove_files(f"{prediction_path}/*.png")
