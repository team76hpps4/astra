import numpy as np
import torch
import yaml
from GRACE.graph_builder import build_ap_graph_v2
from GRACE.trainer import GraceTrainer

with open("GRACE\config\config_5GHz.yaml", "r") as f:
    config = yaml.safe_load(f)

x_mean = torch.tensor(config['x_mean'])
x_std = torch.tensor(config['x_std'])
ea_mean = torch.tensor(config['ea_mean'])
ea_std = torch.tensor(config['ea_std'])

def normalize_new_graph(g, x_mean, x_std, ea_mean, ea_std):
    g.x = (g.x - x_mean) / x_std
    g.edge_attr = (g.edge_attr - ea_mean) / ea_std
    return g

device = "cuda" if torch.cuda.is_available() else "cpu"

trainer = GraceTrainer(
        in_dim=107,
        hidden_dim=128,
        proj_dim=64,
        tau=0.2,
        lr=1e-3,
        weight_decay=1e-5,
        device=device
    )

trainer.load_weights("GRACE/model_weights/grace_model_5GHz.pth")

def get_embeddings(out, overlap, rssi, x_mean=x_mean, x_std=x_std, ea_mean=ea_mean, ea_std=ea_std, trainer=trainer, config=config):
    graph = build_ap_graph_v2(
                    node_features=out,
                    rssi_matrix=torch.tensor(rssi, dtype=torch.float32),
                    overlap_matrix=torch.tensor(overlap, dtype=torch.float32)
                )
    graph = normalize_new_graph(graph, x_mean, x_std, ea_mean, ea_std)
    z = trainer.get_embeddings(graph)
    print("embedding matrix=",z)
    return z
