"""
visualizer.py - Full visualization toolkit for WiFi RRM embeddings
Supports:
 - static Matplotlib visualizations (PCA / t-SNE)
 - interactive Plotly visualization (zoom/pan/hover) and export to HTML
 - embedding movie over epochs (MP4 via ffmpeg or GIF fallback)

Usage examples (see bottom of file):
  - full_visualization(...)
  - plotly_interactive(...)
  - create_embedding_movie(emb_history, ...)
"""

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import plotly.express as px
import plotly.graph_objs as go

# Optional fallback writer
try:
    import imageio
except Exception:
    imageio = None

# -------------------------
# Utilities
# -------------------------
def to_numpy(x):
    import torch
    if 'torch' in globals() and isinstance(x, getattr(__import__('torch'), 'Tensor')):
        return x.detach().cpu().numpy()
    try:
        import torch as _torch
        if isinstance(x, _torch.Tensor):
            return x.detach().cpu().numpy()
    except Exception:
        pass
    return np.array(x)


# -------------------------
# Dim reduction
# -------------------------
def reduce_dim(embeddings, method="pca", n_components=2, random_state=0):
    X = to_numpy(embeddings)
    if method == "pca":
        p = PCA(n_components=n_components, random_state=random_state)
        return p.fit_transform(X)
    elif method == "tsne":
        tsne = TSNE(n_components=n_components, random_state=random_state, init="pca")
        return tsne.fit_transform(X)
    else:
        raise ValueError("method must be 'pca' or 'tsne'")


# -------------------------
# Static Matplotlib plots
# -------------------------
def plot_embeddings_2d(embeddings, labels=None, method="pca",
                       title="Embedding Visualization", node_ids=None,
                       figsize=(8,8), show=True):
    X2 = reduce_dim(embeddings, method=method)
    X2 = np.asarray(X2)
    plt.figure(figsize=figsize)
    ax = plt.gca()
    if labels is None:
        ax.scatter(X2[:,0], X2[:,1], s=50)
    else:
        labels = np.asarray(labels)
        unique = np.unique(labels)
        for u in unique:
            mask = labels == u
            ax.scatter(X2[mask,0], X2[mask,1], s=50, label=f"cluster {u}")
        ax.legend()
    if node_ids is not None:
        for i, nid in enumerate(node_ids):
            ax.text(X2[i,0], X2[i,1], str(nid), fontsize=8)
    ax.set_title(title)
    plt.tight_layout()
    if show:
        plt.show()
    return X2


def plot_embeddings_with_edges(embeddings, edge_index, edge_attr, labels=None,
                               method="pca", title="Embedding + Edge Overlay",
                               figsize=(8,8), show=True):
    X2 = reduce_dim(embeddings, method=method)
    X2 = np.asarray(X2)
    ei = to_numpy(edge_index)

    # ---- UPDATED ----
    # use edge_attr[:,0] as continuous weight (RSSI/interference)
    ea = to_numpy(edge_attr)[:, 0]

    plt.figure(figsize=figsize)
    ax = plt.gca()
    if labels is None:
        ax.scatter(X2[:,0], X2[:,1], s=50)
    else:
        labels = np.asarray(labels)
        unique = np.unique(labels)
        for u in unique:
            mask = labels == u
            ax.scatter(X2[mask,0], X2[mask,1], s=50, label=f"cluster {u}")
        ax.legend()

    for k in range(ei.shape[1]):
        i = int(ei[0,k]); j = int(ei[1,k]); w = float(ea[k])
        lw = 0.5 + 3.0 * np.clip(w, 0.0, 1.0)
        ax.plot([X2[i,0], X2[j,0]],[X2[i,1], X2[j,1]], linewidth=lw, alpha=0.4)

    ax.set_title(title)
    plt.tight_layout()
    if show:
        plt.show()
    return X2


def plot_embedding_similarity_heatmap(embeddings, title="Embedding Cosine Similarity"):
    X = to_numpy(embeddings)
    sim = X @ X.T
    norms = np.linalg.norm(X, axis=1)
    sim = sim / (norms.reshape(-1,1) * norms.reshape(1,-1) + 1e-10)
    plt.figure(figsize=(7,6))
    plt.imshow(sim, cmap="viridis")
    plt.colorbar()
    plt.title(title)
    plt.tight_layout()
    plt.show()
    return sim


def plot_edge_weight_heatmap(edge_index, edge_attr, N, title="AP Interference Heatmap"):
    EI = to_numpy(edge_index)

    # ---- UPDATED ----
    # use column 0
    E = to_numpy(edge_attr)[:, 0]

    mat = np.zeros((N,N))
    for k in range(EI.shape[1]):
        i = EI[0,k]; j = EI[1,k]; w = E[k]
        mat[i,j] = w
    plt.figure(figsize=(7,6))
    plt.imshow(mat, cmap="magma")
    plt.colorbar()
    plt.title(title)
    plt.tight_layout()
    plt.show()
    return mat


# -------------------------
# Plotly interactive
# -------------------------
def plotly_interactive(embeddings, edge_index=None, edge_attr=None, labels=None,
                       node_ids=None, method="pca", title="Interactive Embeddings",
                       html_out=None):
    X2 = reduce_dim(embeddings, method=method)
    X2 = np.asarray(X2)
    N = X2.shape[0]

    df = {
        "x": X2[:,0].tolist(),
        "y": X2[:,1].tolist(),
        "index": list(range(N)),
    }
    if labels is not None:
        df["label"] = labels
    if node_ids is not None:
        df["node_id"] = node_ids
    import pandas as pd
    pdf = pd.DataFrame(df)

    # base scatter
    if labels is None:
        fig = px.scatter(pdf, x="x", y="y", hover_data=["index", "node_id"] if node_ids else ["index"])
    else:
        fig = px.scatter(pdf, x="x", y="y", color="label",
                         hover_data=["index", "node_id"] if node_ids else ["index"])

    # edges
    if edge_index is not None and edge_attr is not None:
        ei = to_numpy(edge_index)

        # ---- UPDATED ----
        ea = to_numpy(edge_attr)[:, 0]

        line_x = []
        line_y = []
        for k in range(ei.shape[1]):
            i = int(ei[0,k]); j = int(ei[1,k])
            line_x += [X2[i,0], X2[j,0], None]
            line_y += [X2[i,1], X2[j,1], None]

        fig.add_trace(go.Scatter(
            x=line_x, y=line_y, mode='lines',
            line=dict(color='rgba(50,50,50,0.4)', width=1),
            hoverinfo='none', showlegend=False
        ))

    fig.update_layout(title=title, width=900, height=700)
    if html_out:
        fig.write_html(html_out)
    return fig


# -------------------------
# Embedding Movie / Animation
# -------------------------
def create_embedding_movie(embeddings_history, edge_index=None, edge_attr=None,
                           method="pca", out_path="embedding_movie.mp4",
                           fps=6, dpi=150, cmap='viridis', node_ids=None,
                           show_progress=True):

    H = [to_numpy(e) for e in embeddings_history]
    epochs = len(H)
    if epochs == 0:
        raise ValueError("embeddings_history is empty")

    N = H[0].shape[0]
    all_emb = np.vstack(H)

    if method == "pca":
        p = PCA(n_components=2, random_state=0)
        all2 = p.fit_transform(all_emb)
    elif method == "tsne":
        from sklearn.manifold import TSNE
        ts = TSNE(n_components=2, random_state=0, init='pca')
        all2 = ts.fit_transform(all_emb)
    else:
        raise ValueError("method must be 'pca' or 'tsne'")

    frames = [all2[i*N:(i+1)*N] for i in range(epochs)]

    fig, ax = plt.subplots(figsize=(8,8), dpi=dpi)
    scatter = ax.scatter(frames[0][:,0], frames[0][:,1], s=50)
    title = ax.text(0.5, 1.01, f"Epoch 0", transform=ax.transAxes, ha="center")

    # edges
    ei = None; ea = None
    if edge_index is not None and edge_attr is not None:
        ei = to_numpy(edge_index)

        # ---- UPDATED ----
        ea = to_numpy(edge_attr)[:, 0]

        edge_lines = []
        for k in range(ei.shape[1]):
            i = int(ei[0,k]); j = int(ei[1,k]); w = float(ea[k])
            lw = 0.5 + 3.0 * np.clip(w, 0.0, 1.0)
            line, = ax.plot(
                [frames[0][i,0], frames[0][j,0]],
                [frames[0][i,1], frames[0][j,1]],
                linewidth=lw, color='gray', alpha=0.35
            )
            edge_lines.append(line)

    ax.set_xticks([]); ax.set_yticks([])

    def update(frame_idx):
        pts = frames[frame_idx]
        scatter.set_offsets(pts)
        title.set_text(f"Epoch {frame_idx+1}/{epochs}")
        if ei is not None:
            for k, line in enumerate(edge_lines):
                i = int(ei[0,k]); j = int(ei[1,k])
                line.set_data([pts[i,0], pts[j,0]],
                              [pts[i,1], pts[j,1]])
        return (scatter, title) + (tuple(edge_lines) if ei is not None else ())

    anim = animation.FuncAnimation(fig, update, frames=epochs,
                                   interval=1000/fps, blit=False)

    out_ext = os.path.splitext(out_path)[1].lower()
    try:
        if out_ext == ".mp4" or out_ext == ".m4v":
            Writer = animation.writers['ffmpeg']
            writer = Writer(fps=fps, metadata=dict(artist='GRACE'), bitrate=1800)
            anim.save(out_path, writer=writer, dpi=dpi)
        elif out_ext == ".gif":
            # fallback GIF rendering via imageio
            if imageio is None:
                raise RuntimeError("imageio is required to save GIF fallback.")
            images = []
            for i in range(epochs):
                update(i)
                fig.canvas.draw()
                image = np.frombuffer(fig.canvas.tostring_rgb(), dtype='uint8')
                image = image.reshape(fig.canvas.get_width_height()[::-1] + (3,))
                images.append(image)
            imageio.mimsave(out_path, images, fps=fps)
        else:
            Writer = animation.writers['ffmpeg']
            writer = Writer(fps=fps, metadata=dict(artist='GRACE'), bitrate=1800)
            anim.save(out_path, writer=writer, dpi=dpi)
    except Exception as e:
        plt.close(fig)
        raise RuntimeError(f"Failed to save animation to {out_path}: {e}")

    plt.close(fig)
    if show_progress:
        print(f"Saved embedding movie to {out_path}")
    return out_path


# -------------------------
# Full Visualization Pipeline
# -------------------------
def full_visualization(embeddings, edge_index, edge_attr, node_ids=None,
                       n_clusters=4, method="pca"):
    emb = to_numpy(embeddings)
    km = KMeans(n_clusters=n_clusters, n_init=10)
    labels = km.fit_predict(StandardScaler().fit_transform(emb))

    print(">> Running full visualization (matplotlib static)...")
    plot_embeddings_2d(emb, labels=labels, method=method,
                       title="AP Embeddings (2D Projection)", node_ids=node_ids)
    plot_embeddings_with_edges(emb, edge_index=edge_index, edge_attr=edge_attr,
                               labels=labels, method=method,
                               title="AP Embeddings + Interference Edges")
    plot_embedding_similarity_heatmap(emb, title="Embedding Cosine Similarity Heatmap")
    N = emb.shape[0]
    plot_edge_weight_heatmap(edge_index, edge_attr, N=N,
                             title="AP Interference Weight Heatmap")
    print(">> Visualization complete.")