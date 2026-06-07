import torch
from torch_geometric.loader import DataLoader
from GRACE.trainer import GraceTrainer, flatten_params, load_all_graphs, compute_normalization_stats, apply_normalization

if __name__ == "__main__":

    device = "cuda" if torch.cuda.is_available() else "cpu"

    graphs = load_all_graphs("Datasets/gnn_2.4GHz_filtered/gnn_2.4GHz")
    x_mean, x_std, ea_mean, ea_std = compute_normalization_stats(graphs)
    apply_normalization(graphs, x_mean, x_std, ea_mean, ea_std)

    batch_size = 32
    loader = DataLoader(graphs, batch_size=batch_size, shuffle=True)

    trainer = GraceTrainer(
        in_dim=59,
        hidden_dim=128,
        proj_dim=64,
        tau=0.2,
        lr=1e-3,
        weight_decay=1e-5,
        device=device
    )

    prev_params = flatten_params(trainer.model)

    epochs = 50
    for epoch in range(epochs):
        total_loss = 0.0
        num_batches = 0

        print(f'\nEpoch {epoch+1} started')
        for batch in loader:
            loss = trainer.train_step(batch)
            total_loss += loss
            num_batches += 1

        avg_loss = total_loss / num_batches

        # ---- CHECK PARAMETER CHANGE THIS EPOCH ----
        curr_params = flatten_params(trainer.model)
        diff = (curr_params - prev_params).norm().item()
        print(f"Epoch {epoch+1}/{epochs} | "
              f"Avg Loss = {avg_loss:.4f} | "
              f"Param L2 change = {diff:.6e}")

        if diff < 1e-9:
            print("  WARNING: parameters barely changed this epoch (check lr / grads).")

        prev_params = curr_params.clone()
        current_lr = trainer.scheduler.get_last_lr()[0]
        print(f"Learning rate: {current_lr:.6f}")
        trainer.scheduler.step()

    z = trainer.get_embeddings(graphs[-1])
    print("\nFinal embeddings for last snapshot:\n", z)