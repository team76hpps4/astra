import os
import glob
import numpy as np

import torch
import torch.optim as optim
import torch.nn.functional as F_

from GRACE.model import Model, EdgeGATEncoder, drop_feature, drop_edge
from GRACE.graph_builder import build_ap_graph_v2
from torch_geometric.loader import DataLoader

import torch.nn.functional as F_
# -------------------------------------------------------------------------
#  HELPER: FLATTEN MODEL PARAMETERS
# -------------------------------------------------------------------------
def flatten_params(model):
    """Return a single 1D tensor of all model parameters."""
    with torch.no_grad():
        return torch.cat([p.view(-1) for p in model.parameters()])


# -------------------------------------------------------------------------
#  GRACE TRAINER
# -------------------------------------------------------------------------
class GraceTrainer:
    def __init__(
        self,
        in_dim,
        hidden_dim=128,
        proj_dim=64,
        tau=0.4,
        lr=1e-3,
        weight_decay=1e-5,
        device='cpu'
    ):
        self.device = torch.device(device)

        encoder = EdgeGATEncoder(
            in_channels=in_dim,
            hidden_dim=hidden_dim,
            activation=F_.relu,
            k=2,
            heads=2,
        )

        self.model = Model(
            encoder=encoder,
            num_hidden=hidden_dim,
            num_proj_hidden=proj_dim,
            tau=tau
        ).to(self.device)

        self.optimizer = optim.Adam(
            self.model.parameters(),
            lr=lr,
            weight_decay=weight_decay
        )

        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, 
            T_max=50   # or pass variable
        )

    def _make_views(self, x, edge_index, edge_attr,
                    feat_drop=0.15, edge_drop=0.05):
        x1 = drop_feature(x, feat_drop)
        eidx1, eattr1 = drop_edge(edge_index, edge_attr, edge_drop)

        x2 = drop_feature(x, feat_drop)
        eidx2, eattr2 = drop_edge(edge_index, edge_attr, edge_drop)

        return x1, eidx1, eattr1, x2, eidx2, eattr2

    def train_step(self, data,
                   feat_drop=0.15,
                   edge_drop=0.05):

        x, edge_index, edge_attr = (
            data.x.to(self.device),
            data.edge_index.to(self.device),
            data.edge_attr.to(self.device),
        )

        x1, eidx1, eattr1, x2, eidx2, eattr2 = self._make_views(
            x, edge_index, edge_attr,
            feat_drop, edge_drop
        )

        z1 = self.model(x1, eidx1, eattr1)
        z2 = self.model(x2, eidx2, eattr2)


        loss = self.model.loss(z1, z2)

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        return loss.item()

    def get_embeddings(self, data):
        self.model.eval()
        with torch.no_grad():
            x = data.x.to(self.device)
            edge_index = data.edge_index.to(self.device)
            edge_attr = data.edge_attr.to(self.device)
            z = self.model(x, edge_index, edge_attr)
        return z
    
    def load_weights(self, checkpoint_path):
        state = torch.load(checkpoint_path, map_location=self.device)

        # handle both "raw state_dict" and "wrapped" checkpoints
        if isinstance(state, dict) and "model_state_dict" in state:
            self.model.load_state_dict(state["model_state_dict"])
        else:
            self.model.load_state_dict(state)

        self.model.eval()


# -------------------------------------------------------------------------
#  DATA LOADING FROM SNAPSHOT FOLDERS
# -------------------------------------------------------------------------
def load_graphs_from_itr_folder(base_dir, itr_name):
    itr_path = os.path.join(base_dir, itr_name)
    output_files = sorted(
        glob.glob(os.path.join(itr_path, "snapshot_*_output.npy"))
    )

    graphs = []

    for out_path in output_files:
        prefix = out_path.replace("_output.npy", "")
        overlap_path = prefix + "_overlap.npy"
        rssi_path = prefix + "_rssi.npy"

        node_features = np.load(out_path)      # (F, N)
        node_features = node_features.T        # -> (N, F)
        overlap_matrix = np.load(overlap_path) # (N, N)
        rssi_matrix = np.load(rssi_path)       # (N, N)

        rssi_tensor = torch.tensor(rssi_matrix, dtype=torch.float32)
        overlap_tensor = torch.tensor(overlap_matrix, dtype=torch.float32)

        data = build_ap_graph_v2(
            node_features=node_features,
            rssi_matrix=rssi_tensor,
            overlap_matrix=overlap_tensor
        )
        graphs.append(data)

    return graphs


def load_all_graphs(base_dir):
    all_graphs = []

    if not os.path.isdir(base_dir):
        raise FileNotFoundError(f"{base_dir} not found")

    # Loop rooms folder
    for room in sorted(os.listdir(base_dir)):
        room_path = os.path.join(base_dir, room)
        if not os.path.isdir(room_path) or not room.startswith("rooms_"):
            continue

        print(f"\n📂 Scanning room: {room}")

        # Loop geom folders
        for geom in sorted(os.listdir(room_path)):
            geom_path = os.path.join(room_path, geom)
            if not os.path.isdir(geom_path) or not geom.startswith("geom_"):
                continue

            print(f"   🧩 Loading snapshots from: {geom}")

            # Get snapshot files inside geom folder
            snapshot_files = sorted(glob.glob(os.path.join(geom_path, "snapshot_*_output.npy")))

            for out_path in snapshot_files:
                prefix = out_path.replace("_output.npy", "")
                overlap_path = prefix + "_overlap.npy"
                rssi_path = prefix + "_rssi.npy"

                if not (os.path.exists(overlap_path) and os.path.exists(rssi_path)):
                    print(f"⚠ Skipping incomplete snapshot: {prefix}")
                    continue

                out_raw = np.load(out_path)
                overlap_matrix = np.load(overlap_path)
                rssi_matrix = np.load(rssi_path)

                N = rssi_matrix.shape[0]   # number of nodes implied by adjacency

                # Decide whether to transpose or not based on shape match
                if out_raw.shape[0] == N:
                   # already (N, F)
                   node_features = out_raw
                elif out_raw.shape[1] == N:
                   # stored as (F, N), so transpose
                   node_features = out_raw.T
                else:
                   raise ValueError(
                        f"Incompatible shapes for {out_path}: "
                        f"output={out_raw.shape}, rssi={rssi_matrix.shape}"
                   )

                # Final safety check
                assert node_features.shape[0] == rssi_matrix.shape[0] == overlap_matrix.shape[0], \
                       f"Node count mismatch in {out_path}: " \
                       f"features={node_features.shape}, " \
                       f"rssi={rssi_matrix.shape}, overlap={overlap_matrix.shape}"

                graph = build_ap_graph_v2(
                    node_features=node_features,
                    rssi_matrix=torch.tensor(rssi_matrix, dtype=torch.float32),
                    overlap_matrix=torch.tensor(overlap_matrix, dtype=torch.float32)
                )

                all_graphs.append(graph)

    if len(all_graphs) == 0:
        raise RuntimeError("❌ No graphs found. Check folder names or file patterns.")

    print(f"\n✅ Total graphs loaded: {len(all_graphs)}")
    return all_graphs

def compute_normalization_stats(graphs):
    xs = []
    edge_attrs = []

    for g in graphs:
        xs.append(g.x)                # [Ni, F]
        edge_attrs.append(g.edge_attr)  # [Ei, 2]

    X = torch.cat(xs, dim=0)           # [N_total, F]
    EA = torch.cat(edge_attrs, dim=0)  # [E_total, 2]

    x_mean = X.mean(dim=0)
    x_std  = X.std(dim=0) + 1e-6       # avoid /0

    ea_mean = EA.mean(dim=0)
    ea_std  = EA.std(dim=0) + 1e-6

    return x_mean, x_std, ea_mean, ea_std


def apply_normalization(graphs, x_mean, x_std, ea_mean, ea_std):
    for g in graphs:
        g.x = (g.x - x_mean) / x_std
        g.edge_attr = (g.edge_attr - ea_mean) / ea_std