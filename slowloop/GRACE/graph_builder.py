import torch
from torch_geometric.data import Data


def normalize_rssi(x, min_v=-200.0, max_v=-30.0):
    """Normalize RSSI/interference to [0,1]."""
    x = torch.clamp(x, min=min_v, max=max_v)
    return (x - min_v) / (max_v - min_v)


def build_ap_graph_v2(
    node_features: torch.Tensor,            # shape: [N, 59]
    rssi_matrix: torch.Tensor,              # shape: [N, N], float
    overlap_matrix: torch.Tensor            # shape: [N, N], {0,1}
) -> Data:
    """
    Build PyG graph from:
      - node_features: 59×N
      - rssi_matrix:   NxN float (interference)
      - overlap_matrix: NxN binary (channel overlap)

    RETURNS:
        Data with:
            x: [N, 59]
            edge_index: [2, E]
            edge_attr: [E, 2]
    """
    # ---- Convert to tensors if needed ----
    if not isinstance(node_features, torch.Tensor):
        node_features = torch.tensor(node_features, dtype=torch.float32)

    if not isinstance(rssi_matrix, torch.Tensor):
        rssi_matrix = torch.tensor(rssi_matrix, dtype=torch.float32)

    if not isinstance(overlap_matrix, torch.Tensor):
        overlap_matrix = torch.tensor(overlap_matrix, dtype=torch.float32)

    # ---- 1. Node features ----
    x = node_features.float()   # [N, 59]
    N = x.size(0)

    # ---- 2. Build edges from RSSI & overlap ----
    # We create edges for all pairs where RSSI is non-zero or overlap is 1
    # (You can change this logic if required)

    # Flatten upper triangle or use all-pairs?
    # Here: use all edges where interference exists
    mask = (rssi_matrix != 0) | (overlap_matrix != 0)
    mask = mask.bool()

    src, dst = mask.nonzero(as_tuple=True)

    # ---- 3. Edge attributes ----
    # Normalize RSSI values
    rssi_norm = normalize_rssi(rssi_matrix[src, dst])

    # Channel overlap is already 0/1
    overlap_vals = overlap_matrix[src, dst].float()

    # Final edge_attr (E, 2)
    edge_attr = torch.stack([rssi_norm, overlap_vals], dim=1)

    # ---- 4. Build edge_index ----
    edge_index = torch.stack([src, dst], dim=0)  # (2, E)

    # ---- 5. Return PyG graph ----
    return Data(
        x=x,
        edge_index=edge_index,
        edge_attr=edge_attr
    )