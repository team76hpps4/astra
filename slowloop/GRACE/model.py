import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv


class EdgeGATEncoder(nn.Module):
    """
    Edge-aware GATv2 encoder.
    Expects edge_attr of size [E, 2] (RSSI + channel_overlap)
    """

    def __init__(self, in_channels, hidden_dim, activation, k=2, heads=2):
        super().__init__()
        assert k >= 1
        self.k = k
        self.activation = activation

        self.layers = nn.ModuleList()

        # First layer
        self.layers.append(
            GATv2Conv(
                in_channels=in_channels,
                out_channels=hidden_dim,
                heads=heads,
                concat=False,
                edge_dim=2     # IMPORTANT
            )
        )

        # Middle layers
        for _ in range(1, k):
            self.layers.append(
                GATv2Conv(
                    in_channels=hidden_dim,
                    out_channels=hidden_dim,
                    heads=heads,
                    concat=False,
                    edge_dim=2    # IMPORTANT
                )
            )

    def forward(self, x, edge_index, edge_attr):
        """
        x: [N, F]
        edge_index: [2, E]
        edge_attr: [E, 2]
        """
        for i, conv in enumerate(self.layers):
            x = conv(x, edge_index, edge_attr)
            if i < len(self.layers) - 1:
              x = self.activation(x)
        return x


# -------------------------------------------------------------------------
#  GRACE MODEL WRAPPER
# -------------------------------------------------------------------------
class Model(torch.nn.Module):
    def __init__(self, encoder, num_hidden, num_proj_hidden, tau: float = 0.2):
        super(Model, self).__init__()
        self.encoder = encoder
        self.tau = tau

        # Projection head (2-layer MLP)
        self.fc1 = torch.nn.Linear(num_hidden, num_proj_hidden)
        self.fc2 = torch.nn.Linear(num_proj_hidden, num_hidden)

    # Forward returns node embeddings
    def forward(self, x, edge_index, edge_attr):
        return self.encoder(x, edge_index, edge_attr)

    # GRACE projection head
    def projection(self, z):
        z = F.elu(self.fc1(z))
        return self.fc2(z)

    # Cosine similarity matrix
    def sim(self, z1, z2):
        z1 = F.normalize(z1)
        z2 = F.normalize(z2)
        return torch.mm(z1, z2.t())

    # GRACE semi-loss
    def semi_loss(self, z1, z2):
        sim_matrix = self.sim(z1, z2) / self.tau
        exp_sim = torch.exp(sim_matrix)

        positives = exp_sim.diag()

        denom = exp_sim.sum(dim=1) - positives + exp_sim.sum(dim=0) - positives

        return -torch.log(positives / denom)

    # Batched version (for large graphs)
    def batched_semi_loss(self, z1, z2, batch_size):
        device = z1.device
        num_nodes = z1.size(0)
        num_batches = (num_nodes - 1) // batch_size + 1

        f = lambda x: torch.exp(x / self.tau)
        indices = torch.arange(0, num_nodes).to(device)
        losses = []

        for i in range(num_batches):
            mask = indices[i * batch_size: (i + 1) * batch_size]
            refl_sim = f(self.sim(z1[mask], z1))
            between_sim = f(self.sim(z1[mask], z2))

            losses.append(-torch.log(
                between_sim[:, i * batch_size:(i + 1) * batch_size].diag()
                / (refl_sim.sum(1) + between_sim.sum(1)
                   - refl_sim[:, i * batch_size:(i + 1) * batch_size].diag())
            ))

        return torch.cat(losses)

    # Full GRACE loss
    def loss(self, z1, z2, mean=True, batch_size=0):
        h1 = self.projection(z1)
        h2 = self.projection(z2)

        if batch_size == 0:
            l1 = self.semi_loss(h1, h2)
            l2 = self.semi_loss(h2, h1)
        else:
            l1 = self.batched_semi_loss(h1, h2, batch_size)
            l2 = self.batched_semi_loss(h2, h1, batch_size)

        loss = (l1 + l2) * 0.5
        return loss.mean() if mean else loss.sum()


# -------------------------------------------------------------------------
#  FEATURE DROPOUT (for graph augmentation)
# -------------------------------------------------------------------------
def drop_feature(x, drop_prob):
    drop_mask = torch.empty(
        (x.size(1),),
        dtype=torch.float32,
        device=x.device
    ).uniform_(0, 1) < drop_prob

    x = x.clone()
    x[:, drop_mask] = 0
    return x

def drop_edge(edge_index, edge_attr, drop_prob):
    """
    Edge dropout for GRACE.
    Drops edges AND their corresponding edge_attr rows.

    edge_index: [2, E]
    edge_attr:  [E, 1] or [E, F]
    drop_prob: float in [0,1]
    """
    # Random mask: keep edges with probability (1 - drop_prob)
    mask = torch.rand(edge_index.size(1), device=edge_index.device) >= drop_prob

    # Apply mask
    edge_index_dropped = edge_index[:, mask]
    edge_attr_dropped = edge_attr[mask]

    return edge_index_dropped, edge_attr_dropped