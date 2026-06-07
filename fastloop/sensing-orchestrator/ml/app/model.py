import torch
from torch import nn
from torch.nn import functional as F
from pydantic import BaseModel


class WirelessID_CNN(nn.Module):
    def __init__(self):
        super(WirelessID_CNN, self).__init__()

        # 🔹 Convolutional + BatchNorm layers
        self.conv1 = nn.Conv2d(1, 16, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(16)
        self.pool1 = nn.MaxPool2d(2, 2)

        self.conv2 = nn.Conv2d(16, 16, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm2d(16)
        self.pool2 = nn.MaxPool2d(2, 2)

        self.conv3 = nn.Conv2d(16, 16, kernel_size=7, padding=3)
        self.bn3 = nn.BatchNorm2d(16)
        self.pool3 = nn.MaxPool2d(2, 2)

        self.conv4 = nn.Conv2d(16, 32, kernel_size=7, padding=3)
        self.bn4 = nn.BatchNorm2d(32)
        self.pool4 = nn.MaxPool2d(2, 2, ceil_mode=True)

        # 🔹 Dynamically compute fc input size
        with torch.no_grad():
            dummy = torch.zeros(1, 1, 280, 280)
            dummy_out = self._forward_conv_layers(dummy)
            self.flattened_size = dummy_out.view(1, -1).size(1)

        # 🔹 Fully connected layers
        self.fc1 = nn.Linear(self.flattened_size, 1024)
        self.bn_fc1 = nn.BatchNorm1d(1024)
        self.dropout = nn.Dropout(0.5)
        self.fc_output = nn.Linear(1024, 5)

    def _forward_conv_layers(self, x):
        x = self.pool1(F.relu(self.bn1(self.conv1(x))))
        x = self.pool2(F.relu(self.bn2(self.conv2(x))))
        x = self.pool3(F.relu(self.bn3(self.conv3(x))))
        x = self.pool4(F.relu(self.bn4(self.conv4(x))))
        return x

    def forward(self, x):
        x = self._forward_conv_layers(x)
        x = torch.flatten(x, 1)
        x = F.relu(self.bn_fc1(self.fc1(x)))
        x = self.dropout(x)
        output = self.fc_output(x)
        return output


class ModelInput(BaseModel):
    iq_data: list[list[float]]



LABELS = ["bluetooth", "empty", "microwave", "wifi", "zigbee"]

def create_model():
    model = WirelessID_CNN()
    model.load_state_dict(torch.load("./models/best_model.pth", map_location=torch.device("cpu")))
    yield model