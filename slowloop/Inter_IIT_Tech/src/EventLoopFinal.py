import os
import sys
import yaml
import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
from datetime import datetime, time as dt_time
import traceback
from Inter_IIT_Tech.src import DEFAULTS_YAML, AP_LIST, EVENT_TRIGGER_AP_CONFIG, SELECT, TOTAL_STEPS, NOW

def load_defaults(default_data=DEFAULTS_YAML, ap_data = AP_LIST):
    path = default_data
    with open(default_data, "r") as f:
        cfg = yaml.safe_load(f)
    with open(ap_data, "r") as f:
        config = yaml.safe_load(f)

    global_defaults = cfg.get("GLOBAL_DEFAULTS", {})
    event_defaults = cfg.get("EVENT_DEFAULTS", {})
    ap24_list = config.get("2.4G")
    ap5_list = config.get("5G")
    ap_list = {"2.4G":ap24_list, "5G":ap5_list}
    # print(ap_list)

    # Validate
    for band in ("2.4G", "5G"):
        if band not in event_defaults:
            raise KeyError(f"Missing band '{band}' under EVENT_DEFAULTS in {path}")
        for profile in ("very_busy", "moderate_busy", "low_busy"):
            if profile not in event_defaults[band]:
                raise KeyError(f"Missing profile '{profile}' for band '{band}' in {path}")

    return global_defaults, event_defaults, ap_list


class EventConfigGUI:
    """
    GUI that supports per-AP custom overrides (Option D-1).
    """

    def __init__(self, global_defaults, event_defaults, ap_list):
        self.global_defaults = global_defaults
        self.event_defaults = event_defaults  # dict: band -> profile -> params
        self.ap_list = ap_list                # dict: band -> [ap names]
        self.result = None

        # per-ap variable store:
        # ap_name -> { "use_custom": BooleanVar, "params": { param_name: StringVar } }
        self.per_ap_vars = {}

        # build root
        self.root = tk.Tk()
        self.root.title("Event Loop Configuration — Per-AP Overrides")
        self.root.geometry("950x720")

        self.build_gui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.root.mainloop()

    
    def build_gui(self):
        pad = {"padx": 8, "pady": 6}

        # Top: Profile selection (global)
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Profile:").pack(side="left", padx=6)
        self.profile_var = tk.StringVar(value="very_busy")
        self.profile_combo = ttk.Combobox(
            top,
            values=["very_busy", "moderate_busy", "low_busy"],
            textvariable=self.profile_var,
            state="readonly",
            width=18,
        )
        self.profile_combo.pack(side="left", padx=6)
        ttk.Button(top, text="Reload profile defaults", command=self.rebuild_ap_sections).pack(side="left", padx=6)

        # Preview / Submit buttons (top-right)
        btn_top = ttk.Frame(top)
        btn_top.pack(side="right")
        ttk.Button(btn_top, text="Preview AP_CONFIGS", command=self.preview_ap_configs).pack(side="left", padx=6)
        ttk.Button(btn_top, text="Submit", command=self.on_submit).pack(side="left", padx=6)
        ttk.Button(btn_top, text="Cancel", command=self.on_cancel).pack(side="left", padx=6)

        # Middle: AP sections (scrollable)
        ap_frame = ttk.LabelFrame(self.root, text="Per-AP Overrides (check 'Use custom' to enable custom params)")
        ap_frame.pack(fill="both", expand=True, padx=8, pady=6)

        canvas = tk.Canvas(ap_frame)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(ap_frame, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.ap_container = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self.ap_container, anchor="nw")

        # Build initial per-AP sections
        self.rebuild_ap_sections()

        # Bottom: Duration
        time_frame = ttk.LabelFrame(self.root, text="Event Duration (end time)")
        time_frame.pack(fill="x", padx=8, pady=6)
        ttk.Label(time_frame, text="End date:").pack(side="left", padx=6)
        self.date_entry = DateEntry(time_frame)
        self.date_entry.pack(side="left", padx=6)
        ttk.Label(time_frame, text="Hour:").pack(side="left", padx=6)
        self.hour_spin = ttk.Spinbox(time_frame, from_=0, to=23, width=4)
        self.hour_spin.set("23")
        self.hour_spin.pack(side="left")
        ttk.Label(time_frame, text="Min:").pack(side="left", padx=6)
        self.min_spin = ttk.Spinbox(time_frame, from_=0, to=59, width=4)
        self.min_spin.set("59")
        self.min_spin.pack(side="left")
        ttk.Label(time_frame, text="Sec:").pack(side="left", padx=6)
        self.sec_spin = ttk.Spinbox(time_frame, from_=0, to=59, width=4)
        self.sec_spin.set("0")
        self.sec_spin.pack(side="left", padx=6)

    # rebuild all per-AP sections (called when profile changes)
    def rebuild_ap_sections(self):
        # clear existing widgets
        for child in self.ap_container.winfo_children():
            child.destroy()
        self.per_ap_vars.clear()

        profile = self.profile_var.get()

        # Group by band
        for band in ("2.4G", "5G"):
            band_label = ttk.Label(self.ap_container, text=f"---- {band} ----", font=("TkDefaultFont", 10, "bold"))
            band_label.pack(anchor="w", padx=6, pady=(8, 2))

            # for each AP in band
            for ap in self.ap_list.get(band, []):
                # container for this AP
                ap_row = ttk.Frame(self.ap_container)
                ap_row.pack(fill="x", padx=10, pady=4, anchor="w")

                # left: AP name and checkbox
                left = ttk.Frame(ap_row)
                left.pack(side="left", fill="y", padx=6)

                ttk.Label(left, text=ap).pack(anchor="w")
                use_var = tk.BooleanVar(value=False)
                chk = ttk.Checkbutton(left, text="Use custom params", variable=use_var)
                chk.pack(anchor="w", pady=(2, 0))

                # right: param frame (hidden unless use_var True)
                right = ttk.Frame(ap_row)
                right.pack(side="left", fill="x", expand=False, padx=12)

                # param fields prefilled with profile defaults
                profile_defaults = self.event_defaults.get(band, {}).get(profile, {})
                param_vars = {}
                # build grid of param entries inside 'right'
                r = 0
                for key, default_val in profile_defaults.items():
                    ttk.Label(right, text=f"{key}:").grid(row=r, column=0, sticky="w", padx=4, pady=2)
                    var = tk.StringVar(value=str(default_val))
                    entry = ttk.Entry(right, textvariable=var, width=18)
                    entry.grid(row=r, column=1, sticky="w", padx=4, pady=2)
                    param_vars[key] = var
                    r += 1

                # by default hide param widgets until use_var is checked
                def update_visibility(var=use_var, frame=right):
                    if var.get():
                        frame.pack(side="left", fill="x", expand=True, padx=12)
                    else:
                        frame.forget()

                # link checkbox toggle to visibility
                use_var.trace_add("write", lambda *a, v=use_var, f=right: update_visibility(v, f))
                # initialize hidden
                update_visibility(use_var, right)

                # store per-ap vars
                self.per_ap_vars[ap] = {"use_custom": use_var, "params": param_vars}

    # Build final AP_CONFIGS using per-ap overrides and profile defaults (D-1 fallback)
    def build_ap_configs(self):
        profile = self.profile_var.get()
        final = {}

        # for each band & ap, compute final
        for band in ("2.4G", "5G"):
            defaults = self.event_defaults.get(band, {}).get(profile, {})
            for ap in self.ap_list.get(band, []):
                ap_vars = self.per_ap_vars.get(ap)
                if ap_vars and ap_vars["use_custom"].get():
                    # use per-ap params, but blank => fallback to defaults
                    params_out = {}
                    for k, default_val in defaults.items():
                        s = ap_vars["params"].get(k)
                        if s is None:
                            # missing param (shouldn't happen) -> fallback
                            params_out[k] = default_val
                            continue
                        txt = s.get().strip()
                        if txt == "":
                            params_out[k] = default_val
                        else:
                            # parse number types when possible based on default type
                            if isinstance(default_val, int):
                                try:
                                    params_out[k] = int(float(txt))
                                except:
                                    params_out[k] = default_val
                            elif isinstance(default_val, float):
                                try:
                                    params_out[k] = float(txt)
                                except:
                                    params_out[k] = default_val
                            else:
                                params_out[k] = txt
                    final[ap] = params_out
                else:
                    # not custom -> copy band/profile defaults
                    final[ap] = defaults.copy()

        return final

    def preview_ap_configs(self):
        try:
            ap_configs = self.build_ap_configs()
            win = tk.Toplevel(self.root)
            win.title("AP_CONFIGS Preview")
            text = tk.Text(win, wrap="none", width=120, height=36)
            text.pack(fill="both", expand=True)
            text.insert("1.0", yaml.safe_dump(ap_configs, sort_keys=False))
            text.configure(state="disabled")
        except Exception as e:
            messagebox.showerror("Preview Error", f"{e}\n\n{traceback.format_exc()}")

    def get_selected_aps(self):
        # APs with custom True
        return [ap for ap, v in self.per_ap_vars.items() if v["use_custom"].get()]

    def get_run_until(self):
        d = self.date_entry.get_date()
        try:
            h = int(self.hour_spin.get())
            m = int(self.min_spin.get())
            s = int(self.sec_spin.get())
        except:
            h, m, s = 23, 59, 0
        return datetime.combine(d, dt_time(h, m, s))

    def on_submit(self):
        try:
            ap_configs = self.build_ap_configs()
            cfg = {
                "profile": self.profile_var.get(),
                "selected_aps": self.get_selected_aps(),
                "AP_CONFIGS": ap_configs,
                "run_until": self.get_run_until(),
                "timestamp": datetime.utcnow(),
            }
            self.result = cfg
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("Submit Error", f"{e}\n\n{traceback.format_exc()}")

    def on_cancel(self):
        self.result = None
        self.root.destroy()


# ----------------- Example event loop & apply -----------------
# def long_running_task_iteration(i):
#     import time
#     time.sleep(0.8)
#     print(f"Working... iteration {i}")


# def apply_config_to_system(cfg):
#     print("\n=== APPLY CONFIG ===")
#     print(yaml.safe_dump(cfg, sort_keys=False))
#     print("====================\n")


# def event_loop():
    
#     global_defaults, event_defaults, ap_list = load_defaults(DEFAULTS_YAML)

#     i = 0
#     while True:
#         try:
#             i += 1
#             long_running_task_iteration(i)
#         except KeyboardInterrupt:
#             print("\nKeyboardInterrupt → opening GUI...")
#             gui = EventConfigGUI(global_defaults, event_defaults, ap_list)
#             cfg = gui.result
#             if cfg is None:
#                 print("GUI canceled. Continuing...")
#                 continue
#             apply_config_to_system(cfg)
#             EVENT_TRIGGER_AP_CONFIG = cfg['AP_CONFIGS']
#             # print(EVENT_TRIGGER_AP_CONFIG)
#             EVENT_TRIGGER_TIME = cfg["run_until"]
#             print("Config active for:", EVENT_TRIGGER_TIME - NOW)

# if __name__ == "__main__":
#     event_loop()
