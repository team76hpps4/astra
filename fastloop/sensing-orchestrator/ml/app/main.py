from app.model import WirelessID_CNN, create_model, ModelInput, LABELS
from app.image_stats import ImageStats, get_statistics
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
import numpy as np
import torch
from torch.nn import functional as F
from torchvision import transforms
import time
import math


app = FastAPI()
resize_transform = transforms.Resize((280, 280))


def sanitize_floats(obj):
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return 0# or 0, or "NaN", depending on what makes sense
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(x) for x in obj]
    return obj


@app.get("/api/inference")
async def get_inference(data: ModelInput, model: WirelessID_CNN = Depends(create_model)):
    start = time.perf_counter() 
    image = torch.from_numpy(np.array(data.iq_data).reshape((280, 70))).float().unsqueeze(0).unsqueeze(0)
    image = resize_transform(image).reshape((1, 1, 280, 280))

    model.eval()
    with torch.no_grad():
        inference = F.softmax(model(image)).tolist()

    print(inference)

    result = []
    for i, inf in enumerate(inference[0]):
        result.append((LABELS[i], inf))

    print(f"Inference time took {time.perf_counter() - start:.6f}s")
    return JSONResponse({"ok": True, "inference": dict(result)})


@app.get("/api/powers")
async def computes_powers(data: ImageStats):
    image = torch.from_numpy(np.array(data.image).reshape((280, 70))).float().numpy()

    interference_power, noise_power, wifi_power, mean_p, std_p, mean_x, mean_y = await get_statistics(image)
    print(mean_y)
    return JSONResponse({ 
                         "interference_power": sanitize_floats(interference_power.item()), 
                         "noise_power": sanitize_floats(noise_power.item()), 
                         "wifi_power": sanitize_floats(wifi_power.item()), 
                         "mean_power": sanitize_floats(float(mean_p)) if mean_p is not None else 0, 
                         "dev_power": sanitize_floats(float(std_p)) if std_p is not None else 0, 
                         "central_freq": sanitize_floats(mean_x.item()) if mean_x is not None else 0, 
                         "duty_cycle": sanitize_floats(mean_y.item()) if mean_y is not None else 0})