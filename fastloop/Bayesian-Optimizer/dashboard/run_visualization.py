"""
visualize_optuna_study.py
-------------------------
Visualizes the results of an Optuna study stored in optuna_study.db.

Usage:
    python visualize_optuna_study.py --storage ./optuna_study.db --study-name wifi_optimization
"""

import optuna
import argparse
import os
from src.helper import get_current_window_index

parser = argparse.ArgumentParser()
parser.add_argument("--storage", type=str, default="./optuna_study.db")
parser.add_argument("--study-name", type=str, default="wifi_optimization")
parser.add_argument("--outdir", type=str, default="./dashboard")
parser.add_argument("--show", action="store_true", help="Open interactive plots in browser")
args = parser.parse_args()

dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard")
os.makedirs(dashboard_dir, exist_ok=True)
optuna_db_path = os.path.join(dashboard_dir, "optuna_window_7.db")
storage_uri = f"sqlite:///{optuna_db_path}"

print(f"📂 Loading study '{args.study_name}' from {storage_uri}")
study = optuna.load_study(study_name=args.study_name, storage=storage_uri)
os.makedirs(args.outdir, exist_ok=True)

from optuna.visualization import (
    plot_optimization_history,
    plot_parallel_coordinate,
    plot_param_importances,
    plot_contour,
    plot_slice,
)



print("📊 Generating Optuna visualizations...")

fig1 = plot_optimization_history(study)
fig1.write_image(os.path.join(args.outdir, "optimization_history_window7.png"))

fig2 = plot_parallel_coordinate(study)
fig2.write_image(os.path.join(args.outdir, "parallel_coordinates_window7.png"))

fig3 = plot_param_importances(study)
fig3.write_image(os.path.join(args.outdir, "param_importances_window7.png"))

fig4 = plot_contour(study)
fig4.write_image(os.path.join(args.outdir, "contour_plot_window7.png"))

fig5 = plot_slice(study)
fig5.write_image(os.path.join(args.outdir, "slice_plot_window7.png"))

if args.show:
    fig1.show()
    fig2.show()
    fig3.show()
    fig4.show()
    fig5.show()

print(f"✅ All plots saved in '{args.outdir}/'")