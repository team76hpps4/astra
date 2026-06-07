import numpy as np
import cv2 as cv
import torch
from torch.nn import functional as F
from pydantic import BaseModel


MAX_LENGTH = 5

def detect_horizontal_lines(binary_img, max_length):
    highlighted_img = np.stack([binary_img] * 3, axis=-1).astype(np.uint8) * 255
    line_mask = np.zeros_like(binary_img, dtype=np.uint8)

    for row_idx in range(binary_img.shape[0]):
        row = binary_img[row_idx, :]
        padded = np.concatenate(([1], row, [1]))
        diff = np.diff(padded)

        starts = np.where(diff == -1)[0]
        ends = np.where(diff == 1)[0]

        for start, end in zip(starts, ends):
            segment_length = end - start

            if segment_length <= max_length:
                line_mask[row_idx, start:end] = 1
                highlighted_img[row_idx, start:end] = [255, 0, 0]
    line_mask = 1 - line_mask
    return highlighted_img, line_mask


def power_mean_std(wifi):
    signal_mask = wifi != 0
    signal_values = wifi[signal_mask]

    if signal_values.size == 0:
        return 0.0, 0.0, 0.0
    total_power = np.sum(signal_values)
    mean_power = np.mean(signal_values)
    std_power = np.std(signal_values)

    return total_power, mean_power, std_power


async def get_statistics(image):
    image = torch.from_numpy(image).float()
    image_tensor = image.unsqueeze(0).unsqueeze(0)

    vertical_kernel = torch.tensor([[ 0,  0,  0],
                                    [-2.5, -2.5, -2.5],
                                    [ 0,  0,  0]], dtype=torch.float32).unsqueeze(0).unsqueeze(0)

    if image_tensor.is_cuda:
        vertical_kernel = vertical_kernel.to(image_tensor.device)

    gradient_y = F.conv2d(image_tensor, vertical_kernel, padding='same')

    gradient_y_display = gradient_y.squeeze().abs()
    gradient_y_display = (gradient_y_display - gradient_y_display.min()) / (gradient_y_display.max() - gradient_y_display.min())
    #threshold = gradient_y_display.mean() + gradient_y_display.std() * 0.5 # A simple adaptive threshold
    threshold = 0.2
    binary_image = (gradient_y_display <= threshold).float() # Inverted binarization

    binary = binary_image.numpy()

    highlighted_image, horizontal_lines_mask = detect_horizontal_lines(binary, MAX_LENGTH)
    wifi = binary - horizontal_lines_mask

    wifi_intensity = image.numpy() * np.abs(wifi)
    total_power = np.sum(image.numpy() * np.abs(1 - binary))
    wifi_power = np.abs(np.sum(wifi_intensity))
    other_power = total_power - wifi_power

    total_p, mean_p, std_p = power_mean_std(wifi_intensity)


    x_centers = []

    for y in range(wifi.shape[0]):
        row = wifi[y, :]
        zero_start = None

        for x in range(1, len(row) - 1):
            # Detect start of 0 segment (bounded by 1)
            if row[x] == 0 and row[x - 1] == 1:
                zero_start = x

            # Detect end of segment (bounded by 1)
            elif row[x] == 1 and row[x - 1] == 0 and zero_start is not None:
                zero_end = x - 1
                center = (zero_start + zero_end) / 2
                x_centers.append(center)
                zero_start = None

    mean_x = np.mean(x_centers) if x_centers else None


    # ---------------- Vertical (y-wise) ----------------
    y_centers = []

    for x in range(wifi.shape[1]):
        col = wifi[:, x]
        zero_start = None

        for y in range(1, len(col) - 1):
            if col[y] == 0 and col[y - 1] == 1:
                zero_start = y
            elif col[y] == 1 and col[y - 1] == 0 and zero_start is not None:
                zero_end = y - 1
                center = (zero_start + zero_end) / 2
                y_centers.append(center)
                zero_start = None

    mean_y = np.mean(y_centers) if y_centers else None

    mask = torch.from_numpy(binary_image.numpy())
    temp = torch.sum(mask)
    noise = image * mask
    P = torch.sum(image)
    P_noise = torch.sum(noise)
    interference_power = (P - P_noise)/((280**2)-temp)
    noise_power = P_noise/temp

    wifi_pixels = np.abs(np.sum(wifi))
    interference_pixels = np.sum(np.abs(1 - binary)) - np.sum(wifi)
    background_pixels = 280 * 280 - np.sum(np.abs(1 - binary))

    # return (interference_power, noise_power)
    return (other_power / interference_pixels, noise_power / background_pixels, total_p / wifi_pixels, mean_p / wifi_pixels, std_p / wifi_pixels, mean_x, mean_y)


class ImageStats(BaseModel):
    image: list[list[float]]