import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import serial
import serial.tools.list_ports
import threading
import time
import math
import webbrowser 
import json
import sys
import os
import logging

# --- VERSION INFO ---
APP_VERSION = "6.9"
APP_TITLE = f"fabOS - Pedal Manager"

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PedalApp")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def center_window(window, width, height):
    """ Centers a tkinter window on the screen """
    # Get screen width and height
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()

    # Calculate position x and y coordinates
    x = int((screen_width / 2) - (width / 2))
    y = int((screen_height / 2) - (height / 2))

    # Set the dimensions of the screen and where it is placed
    window.geometry(f'{width}x{height}+{x}+{y}')

# Try importing Pillow for high-quality image resizing
try:
    from PIL import Image, ImageTk
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    logger.warning("Pillow (PIL) not found. Image resizing disabled.")

# --- CALIBRATION WIZARD CLASS ---
class CalibrationWizard(tk.Toplevel):
    def __init__(self, parent, pedal_name, prefix):
        super().__init__(parent.root)
        self.parent = parent
        self.pedal_name = pedal_name
        self.prefix = prefix
        self.title(f"Calibrate {pedal_name}")
        
        # Center the wizard on screen
        center_window(self, 500, 450)
        
        self.configure(bg=parent.BG_COLOR)
        
        # Make modal
        self.transient(parent.root)
        self.grab_set()
        
        self.samples = []
        self.is_sampling = False
        self.measured_min = 0
        self.measured_max = 1023
        
        self.create_ui()
        self.update_loop()

    def create_ui(self):
        lbl_title = tk.Label(self, text=f"{self.pedal_name} Calibration Wizard", 
                             font=(self.parent.FONT_FAMILY, 16, "bold"), 
                             bg=self.parent.BG_COLOR, fg=self.parent.PRIMARY_COLOR)
        lbl_title.pack(pady=20)

        self.lbl_instruction = tk.Label(self, text="Step 1: Min Value\n\nRelease the pedal completely.", 
                                        font=(self.parent.FONT_FAMILY, 12), 
                                        bg=self.parent.BG_COLOR, fg=self.parent.TEXT_COLOR,
                                        justify="center", wraplength=450)
        self.lbl_instruction.pack(pady=10)

        self.lbl_live = tk.Label(self, text="Live: 0", font=("Consolas", 14), 
                                 bg=self.parent.CARD_BG, fg=self.parent.ACCENT_COLOR,
                                 width=15, relief="solid", borderwidth=1)
        self.lbl_live.pack(pady=15)

        self.pb_sampling = ttk.Progressbar(self, orient="horizontal", length=400, mode="determinate", style="Horizontal.TProgressbar")
        self.pb_sampling.pack(pady=5)

        self.btn_action = tk.Button(self, text="MEASURE MIN (2s)", 
                                    bg=self.parent.PRIMARY_COLOR, fg="white", 
                                    font=(self.parent.FONT_FAMILY, 12, "bold"),
                                    relief="flat", padx=20, pady=10,
                                    command=self.start_min_capture)
        self.btn_action.pack(pady=20)

        self.lbl_result = tk.Label(self, text="", font=(self.parent.FONT_FAMILY, 10, "italic"), bg=self.parent.BG_COLOR, fg=self.parent.TEXT_COLOR)
        self.lbl_result.pack()

    def update_loop(self):
        if not self.winfo_exists(): return
        if self.prefix == "T": val = self.parent.live_T_val
        elif self.prefix == "B": val = self.parent.live_B_val
        else: val = self.parent.live_C_val
        self.lbl_live.config(text=f"Raw: {val}")
        if self.is_sampling: self.samples.append(val)
        self.after(20, self.update_loop)

    def calculate_smoothed_value(self):
        if not self.samples: return 0
        sorted_samples = sorted(self.samples)
        count = len(sorted_samples)
        trim = int(count * 0.1) 
        if trim > 0 and count > (trim*2):
            clean_samples = sorted_samples[trim:-trim]
        else:
            clean_samples = sorted_samples
        if not clean_samples: return 0
        return int(sum(clean_samples) / len(clean_samples))

    def start_min_capture(self):
        self.samples = []
        self.is_sampling = True
        self.btn_action.config(state="disabled", text="Measuring...")
        self.run_progress(0, "MIN")

    def start_max_capture(self):
        self.samples = []
        self.is_sampling = True
        self.btn_action.config(state="disabled", text="Measuring...")
        self.run_progress(0, "MAX")

    def run_progress(self, step, mode):
        if step <= 100:
            self.pb_sampling['value'] = step
            self.after(20, lambda: self.run_progress(step + 1, mode))
        else:
            self.finish_capture(mode)

    def finish_capture(self, mode):
        self.is_sampling = False
        result = self.calculate_smoothed_value()
        if mode == "MIN":
            self.measured_min = result
            self.lbl_result.config(text=f"Captured Min: {result} (Smoothed)")
            self.lbl_instruction.config(text="Step 2: Max Value\n\nPress and HOLD the pedal fully.")
            self.btn_action.config(state="normal", text="MEASURE MAX (2s)", command=self.start_max_capture)
            self.pb_sampling['value'] = 0
        elif mode == "MAX":
            self.measured_max = result
            self.lbl_result.config(text=f"Captured Max: {result} (Smoothed)")
            self.lbl_instruction.config(text="Calibration Complete!\n\nValues have been applied.")
            self.btn_action.config(state="normal", text="APPLY & CLOSE", command=self.apply_and_close)
            self.pb_sampling['value'] = 100

    def apply_and_close(self):
        getattr(self.parent, f"var_{self.prefix}_min").set(self.measured_min)
        getattr(self.parent, f"var_{self.prefix}_max").set(self.measured_max)
        # This triggers send_pedal_update, which now includes Auto-Save
        self.parent.send_pedal_update(self.prefix)
        self.destroy()


# --- MAIN APPLICATION ---
class PedalApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        
        # Center the main window
        center_window(self.root, 1100, 950)
        
        self.root.minsize(600, 600) 
        
        self.FONT_FAMILY = "Roboto" 
        self.is_dark_mode = False  
        self.PROFILES_DIR = "profiles"
        self.SETTINGS_FILE = "pedal_settings.json" # New settings file
        self.current_active_profile = None # Tracks the currently loaded/saved profile filename
        
        if not os.path.exists(self.PROFILES_DIR):
            try:
                os.makedirs(self.PROFILES_DIR)
            except OSError as e:
                logger.error(f"Failed to create profiles directory: {e}")

        self.set_colors()
        
        self.style = ttk.Style()
        self.style.theme_use('clam') 
        self.configure_styles()

        self.ser = None
        self.is_connected = False

        self.live_T_val = 0
        self.live_B_val = 0
        self.live_C_val = 0
        self.peak_force_session = 0.0
        
        # --- CUSTOM CURVE STORAGE ---
        # 9 points representing 10%, 20%... 90%
        # Values are 0-100 (percentage output)
        self.custom_curves = {
            "T": [10, 20, 30, 40, 50, 60, 70, 80, 90],
            "B": [10, 20, 30, 40, 50, 60, 70, 80, 90],
            "C": [10, 20, 30, 40, 50, 60, 70, 80, 90]
        }
        self.drag_data = {"active": False, "prefix": None, "index": -1}

        self.create_widgets()
        self.update_ui_state() # Initialize UI in locked state

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.running = True
        self.thread = threading.Thread(target=self.serial_loop, name="SerialLoop", daemon=True)
        self.thread.start()
        
        self.root.after(100, self.redraw_all_graphs)
        self.root.after(200, self.load_startup_settings) # Load last profile on startup

    def set_colors(self):
        if self.is_dark_mode:
            self.PRIMARY_COLOR = "#511AEE" 
            self.ACCENT_COLOR = "#005a9e"
            self.BG_COLOR = "#1e1e1e"       
            self.CARD_BG = "#2d2d2d"        
            self.TEXT_COLOR = "#ffffff"     
            self.INACTIVE_TAB = "#333333"   
            self.BORDER_COLOR = "#444444"   
            self.ENTRY_BG = "#404040"       
            self.ENTRY_FG = "#ffffff"
            self.DZ_FILL = "#451515"        # High Vis Red
            self.DZ_LINE = "#ff5555"
            self.GRID_COLOR = "#444444"
        else:
            self.PRIMARY_COLOR = "#511AEE"  
            self.ACCENT_COLOR = "#005a9e"
            self.BG_COLOR = "#ffffff"       
            self.CARD_BG = "#ffffff"        
            self.TEXT_COLOR = "#333333"
            self.INACTIVE_TAB = "#f8f9fa"   
            self.BORDER_COLOR = "#e0e0e0"   
            self.ENTRY_BG = "#ffffff"
            self.ENTRY_FG = "#000000"
            self.DZ_FILL = "#ffe0e0"
            self.DZ_LINE = "#cc0000"
            self.GRID_COLOR = "#e0e0e0"

    def configure_styles(self):
        self.root.configure(bg=self.BG_COLOR)
        
        self.style.configure("TFrame", background=self.BG_COLOR)
        self.style.configure("Card.TFrame", background=self.CARD_BG)
        self.style.configure("TLabel", background=self.BG_COLOR, foreground=self.TEXT_COLOR, font=(self.FONT_FAMILY, 10))
        self.style.configure("Card.TLabel", background=self.CARD_BG, foreground=self.TEXT_COLOR, font=(self.FONT_FAMILY, 10))
        
        self.style.configure("Card.TLabelframe", 
                             background=self.CARD_BG, 
                             relief="solid", 
                             borderwidth=1, 
                             bordercolor=self.BORDER_COLOR)
        self.style.configure("Card.TLabelframe.Label", 
                             background=self.CARD_BG, 
                             foreground=self.PRIMARY_COLOR, 
                             font=(self.FONT_FAMILY, 11, "bold"))

        btn_bg = "#444444" if self.is_dark_mode else "#e8e8e8"
        btn_active = "#555555" if self.is_dark_mode else "#d0d0d0"
        btn_fg = "#ffffff" if self.is_dark_mode else "#000000"
        
        self.style.configure("TButton", 
                             font=(self.FONT_FAMILY, 10), 
                             padding=8, 
                             relief="flat", 
                             borderwidth=0,
                             background=btn_bg,
                             foreground=btn_fg)
        self.style.map("TButton",
            background=[("active", btn_active), ("!active", btn_bg)],
            foreground=[("!active", btn_fg)]
        )
        
        self.style.configure("Primary.TButton", 
                             background=self.PRIMARY_COLOR, 
                             foreground="white", 
                             relief="flat", 
                             padding=10)
        self.style.map("Primary.TButton",
            background=[("active", self.ACCENT_COLOR), ("!active", self.PRIMARY_COLOR)],
            foreground=[("!active", "white")]
        )

        tab_fg = "#cccccc" if self.is_dark_mode else "#666666"
        self.style.configure("TNotebook", background=self.BG_COLOR, borderwidth=0)
        self.style.configure("TNotebook.Tab", 
                             padding=[20, 12], 
                             font=(self.FONT_FAMILY, 11, "bold"), 
                             background=self.INACTIVE_TAB,
                             foreground=tab_fg,
                             borderwidth=0,
                             focuscolor=self.BG_COLOR)
        
        self.style.map("TNotebook.Tab",
            background=[("selected", self.PRIMARY_COLOR), ("!selected", self.INACTIVE_TAB)],
            foreground=[("selected", "white"), ("!selected", tab_fg)],
            font=[("selected", (self.FONT_FAMILY, 11, "bold")), ("!selected", (self.FONT_FAMILY, 11, "bold"))],
            padding=[("selected", [20, 12]), ("!selected", [20, 12])],
            expand=[("selected", [0, 0, 0, 0]), ("!selected", [0, 0, 0, 0])]
        )

        trough = "#404040" if self.is_dark_mode else "#f0f0f0"
        self.style.configure("Horizontal.TProgressbar", background=self.PRIMARY_COLOR, troughcolor=trough, borderwidth=0, thickness=15)

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.set_colors()
        self.configure_styles()
        for widget in self.root.winfo_children():
            widget.destroy()
        self.create_widgets()
        self.redraw_all_graphs()
        self.update_ui_state() # Re-apply locked state after redraw

    def create_widgets(self):
        # 1. Header
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill="x", side="top")
        header_bg = tk.Canvas(header_frame, height=70, bg=self.PRIMARY_COLOR, highlightthickness=0)
        header_bg.pack(fill="x")
        header_bg.create_text(30, 35, text=APP_TITLE, fill="white", font=(self.FONT_FAMILY, 20, "bold"), anchor="w")
        
        theme_text = "🌙" if self.is_dark_mode else "☀️"
        btn_theme = tk.Button(header_frame, text=theme_text, bg=self.PRIMARY_COLOR, fg="white", font=("Segoe UI", 16), borderwidth=0, activebackground=self.ACCENT_COLOR, activeforeground="white", command=self.toggle_theme, cursor="hand2")
        btn_theme.place(relx=1.0, rely=0.5, x=-30, anchor="e") 

        # 2. Footer
        footer_frame = ttk.Frame(self.root, padding=20)
        footer_frame.pack(fill="x", side="bottom")
        self.btn_save_flash = ttk.Button(footer_frame, text="SAVE SETTINGS TO PEDAL MEMORY", style="Primary.TButton", command=self.save_to_eeprom, state="disabled")
        self.btn_save_flash.pack(fill="x", ipady=5)

        # 3. SCROLLABLE CONTAINER
        container_frame = ttk.Frame(self.root)
        container_frame.pack(fill="both", expand=True)
        
        self.canvas = tk.Canvas(container_frame, bg=self.BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container_frame, orient="vertical", command=self.canvas.yview)
        
        self.scrollable_frame = ttk.Frame(self.canvas, style="TFrame")
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", tags="window_frame")
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # --- CONTENT ---

        # A. Connection Bar
        conn_container = ttk.Frame(self.scrollable_frame, padding=20)
        conn_container.pack(fill="x")
        conn_frame = ttk.Frame(conn_container, style="Card.TFrame")
        conn_frame.pack(fill="x", ipady=10)
        conn_border = tk.Frame(conn_container, bg=self.BORDER_COLOR, padx=1, pady=1)
        conn_border.place(in_=conn_frame, x=0, y=0, relwidth=1, relheight=1, anchor="nw", bordermode="outside")
        conn_frame.lift()

        inner_conn = ttk.Frame(conn_frame, style="Card.TFrame")
        inner_conn.pack(fill="x", padx=20, pady=10)

        ttk.Label(inner_conn, text="Port:", style="Card.TLabel").pack(side="left", padx=(0, 10))
        self.port_combo = ttk.Combobox(inner_conn, width=20, font=(self.FONT_FAMILY, 10))
        self.port_combo.pack(side="left", padx=(0, 10))
        self.refresh_ports()
        
        self.btn_refresh = ttk.Button(inner_conn, text="⟳", width=4, command=self.refresh_ports)
        self.btn_refresh.pack(side="left", padx=(0, 15))
        
        self.btn_connect = ttk.Button(inner_conn, text="Connect" if not self.is_connected else "Disconnect", style="Primary.TButton", command=self.toggle_connection)
        self.btn_connect.pack(side="left", padx=(0, 20))

        status_fg = "#28a745" if self.is_connected else "#dc3545"
        status_text = "🟢 Connected" if self.is_connected else "🔴 Not Connected"
        self.lbl_status = tk.Label(inner_conn, text=status_text, fg=status_fg, bg=self.CARD_BG, font=(self.FONT_FAMILY, 10, "bold"))
        self.lbl_status.pack(side="left")

        # B. Profile Manager
        prof_container = ttk.Frame(self.scrollable_frame, padding=20)
        prof_container.pack(fill="x")
        prof_frame = ttk.Frame(prof_container, style="Card.TFrame")
        prof_frame.pack(fill="x", ipady=5)
        prof_border = tk.Frame(prof_container, bg=self.BORDER_COLOR, padx=1, pady=1)
        prof_border.place(in_=prof_frame, x=0, y=0, relwidth=1, relheight=1, anchor="nw", bordermode="outside")
        prof_frame.lift()

        inner_prof = ttk.Frame(prof_frame, style="Card.TFrame")
        inner_prof.pack(fill="x", padx=20, pady=10)
        
        ttk.Label(inner_prof, text="Active Profile:", style="Card.TLabel").pack(side="left", padx=(0, 10))
        self.profile_combo = ttk.Combobox(inner_prof, width=25, font=(self.FONT_FAMILY, 10))
        self.profile_combo.pack(side="left", padx=(0, 10))
        self.refresh_profiles()
        
        self.btn_prof_load = ttk.Button(inner_prof, text="Load", width=8, command=self.load_profile)
        self.btn_prof_load.pack(side="left", padx=(0, 10))
        
        self.btn_prof_save = ttk.Button(inner_prof, text="Save", width=8, command=self.manual_save_profile)
        self.btn_prof_save.pack(side="left", padx=(0, 10))
        
        self.btn_prof_save_as = ttk.Button(inner_prof, text="Save As...", width=12, command=self.save_profile_as)
        self.btn_prof_save_as.pack(side="left", padx=(0, 10))
        
        self.btn_prof_delete = ttk.Button(inner_prof, text="Delete", width=8, command=self.delete_profile)
        self.btn_prof_delete.pack(side="left", padx=(0, 10))

        # C. Main Tabs
        self.notebook = ttk.Notebook(self.scrollable_frame)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        self.about_frame = self.create_about_tab()
        self.notebook.add(self.about_frame, text=" fabPedals ")

        self.throttle_frame = self.create_pedal_tab("Throttle", "T")
        self.notebook.add(self.throttle_frame, text=" Throttle ")
        
        self.brake_frame = self.create_pedal_tab("Brake", "B")
        self.notebook.add(self.brake_frame, text=" Brake ")
        
        self.clutch_frame = self.create_pedal_tab("Clutch", "C")
        self.notebook.add(self.clutch_frame, text=" Clutch ")
        
        self.help_frame = self.create_help_tab()
        self.notebook.add(self.help_frame, text=" Help ")

    def update_ui_state(self):
        """ Enables/Disables critical UI elements based on connection status """
        state = "normal" if self.is_connected else "disabled"
        
        # 1. Main Save Button
        if hasattr(self, 'btn_save_flash'):
            self.btn_save_flash.config(state=state)
        
        # 2. Profile Save Buttons (Prevent editing while disconnected)
        if hasattr(self, 'btn_prof_save'):
            self.btn_prof_save.config(state=state)
            self.btn_prof_save_as.config(state=state)
            
        # 3. Notebook Tabs (Throttle, Brake, Clutch are indices 1, 2, 3)
        # 0 is About, 4 is Help - keep those open
        if hasattr(self, 'notebook'):
            try:
                self.notebook.tab(1, state=state) # Throttle
                self.notebook.tab(2, state=state) # Brake
                self.notebook.tab(3, state=state) # Clutch
            except Exception:
                pass # In case tabs aren't ready yet

    # --- SCROLL LOGIC (FIXED) ---
    def on_canvas_configure(self, event):
        self.canvas.itemconfig("window_frame", width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    # --- PROFILE SYSTEM ---
    def refresh_profiles(self):
        try:
            files = [f.replace(".json", "") for f in os.listdir(self.PROFILES_DIR) if f.endswith(".json")]
            self.profile_combo['values'] = files
            if files:
                self.profile_combo.current(0)
        except Exception:
            logger.exception("refresh_profiles failed")

    def get_current_profile_data(self):
        """ Helper to gather current UI values into a dict """
        return {
            "T": {
                "min": self.var_T_min.get(), "max": self.var_T_max.get(),
                "curve": self.var_T_curve.get(), "dz_bot": self.var_T_dz_bot.get(), "dz_top": self.var_T_dz_top.get(),
                "mode": self.var_T_curve_mode.get(), "custom": self.custom_curves["T"]
            },
            "B": {
                "min": self.var_B_min.get(), "max": self.var_B_max.get(),
                "curve": self.var_B_curve.get(), "dz_bot": self.var_B_dz_bot.get(), "dz_top": self.var_B_dz_top.get(),
                "sensor_rating": self.var_sensor_rating.get(), "calib_force": self.var_calib_force.get(),
                "mode": self.var_B_curve_mode.get(), "custom": self.custom_curves["B"]
            },
            "C": {
                "min": self.var_C_min.get(), "max": self.var_C_max.get(),
                "curve": self.var_C_curve.get(), "dz_bot": self.var_C_dz_bot.get(), "dz_top": self.var_C_dz_top.get(),
                "mode": self.var_C_curve_mode.get(), "custom": self.custom_curves["C"]
            }
        }

    def auto_save_current_profile(self):
        """ Automatically updates the currently loaded profile file without prompting. """
        if not self.current_active_profile:
            return # No profile loaded, nothing to auto-save to.

        try:
            filename = os.path.join(self.PROFILES_DIR, f"{self.current_active_profile}.json")
            data = self.get_current_profile_data()
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Auto-saved profile: {self.current_active_profile}")
        except Exception as e:
            logger.error(f"Auto-save failed: {e}")

    def manual_save_profile(self):
        """ Manually triggered save for the active profile """
        if not self.current_active_profile:
            messagebox.showwarning("Warning", "No profile loaded. Please 'Save As' to create one first.")
            return
        
        try:
            self.auto_save_current_profile()
            messagebox.showinfo("Success", f"Profile '{self.current_active_profile}' saved!")
        except Exception as e:
            messagebox.showerror("Error", f"Save failed: {e}")

    def save_profile_as(self):
        name = simpledialog.askstring("Save Profile", "Enter Profile Name:")
        if name:
            # sanitize filename
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
            if not safe_name:
                messagebox.showerror("Error", "Invalid profile name.")
                return
            filename = os.path.join(self.PROFILES_DIR, f"{safe_name}.json")
            
            data = self.get_current_profile_data()
            
            try:
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=2)
                self.refresh_profiles()
                self.profile_combo.set(safe_name)
                self.current_active_profile = safe_name # Set active profile
                self.save_app_settings() # Remember this profile
                messagebox.showinfo("Success", f"Profile '{safe_name}' saved successfully!")
            except Exception as e:
                logger.exception("save_profile_as failed")
                messagebox.showerror("Error", f"Could not save profile: {e}")

    def load_profile(self):
        name = self.profile_combo.get()
        if not name: return
        
        filename = os.path.join(self.PROFILES_DIR, f"{name}.json")
        if not os.path.exists(filename):
            messagebox.showerror("Error", "Profile not found.")
            return
            
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            def load_section(prefix, section_name):
                d = data.get(section_name, {})
                getattr(self, f"var_{prefix}_min").set(int(d.get("min", 0)))
                getattr(self, f"var_{prefix}_max").set(int(d.get("max", 1023)))
                getattr(self, f"var_{prefix}_curve").set(float(d.get("curve", 1.0)))
                getattr(self, f"var_{prefix}_dz_bot").set(int(d.get("dz_bot", 5)))
                getattr(self, f"var_{prefix}_dz_top").set(int(d.get("dz_top", 5)))
                
                # Load Custom Curve Data
                if hasattr(self, f"var_{prefix}_curve_mode"):
                    getattr(self, f"var_{prefix}_curve_mode").set(int(d.get("mode", 0)))
                
                # Load Points if exist, else default
                raw_pts = d.get("custom", None)
                if raw_pts and isinstance(raw_pts, list) and len(raw_pts) == 9:
                    self.custom_curves[prefix] = raw_pts
                else:
                    self.custom_curves[prefix] = [10, 20, 30, 40, 50, 60, 70, 80, 90]

                # Update Text Label
                lbl = getattr(self, f"lbl_curve_{prefix}", None)
                if lbl: lbl.config(text=f"Gamma: {float(d.get('curve', 1.0)):.2f}")
                
                # Update UI visibility
                self.on_curve_mode_change(prefix)

            load_section("T", "T")
            load_section("B", "B")
            load_section("C", "C")
            
            # Special loading for Brake Specifics
            b = data.get("B", {})
            self.var_sensor_rating.set(int(b.get("sensor_rating", 200)))
            self.var_calib_force.set(float(b.get("calib_force", 65)))

            # Set Active Profile
            self.current_active_profile = name
            self.save_app_settings() # Remember this profile

            # Reset peak force on profile load
            self.peak_force_session = 0.0
            if hasattr(self, "lbl_peak_force"):
                self.lbl_peak_force.config(text="Peak: 0.0 kg")

            # Update UI and Hardware (do hardware writes in background)
            self.redraw_all_graphs()
            def apply_profile():
                try:
                    self.send_pedal_update("T")
                    time.sleep(0.05)
                    self.send_pedal_update("B")
                    time.sleep(0.05)
                    self.send_pedal_update("C")
                except Exception:
                    logger.exception("apply_profile failed")
            threading.Thread(target=apply_profile, daemon=True).start()
            
            messagebox.showinfo("Loaded", f"Profile '{name}' loaded and applied.")
            
        except Exception as e:
            logger.exception("load_profile failed")
            messagebox.showerror("Error", f"Could not load profile: {e}")

    def delete_profile(self):
        name = self.profile_combo.get()
        if not name: return
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete profile '{name}'?"):
            try:
                os.remove(os.path.join(self.PROFILES_DIR, f"{name}.json"))
                self.refresh_profiles()
                self.profile_combo.set("")
                if self.current_active_profile == name:
                    self.current_active_profile = None
                    self.save_app_settings() # Update settings to remove active profile
            except Exception as e:
                logger.exception("delete_profile failed")
                messagebox.showerror("Error", str(e))

    # --- SETTINGS PERSISTENCE ---
    def save_app_settings(self):
        """ Saves the current active profile to a settings file """
        try:
            data = {"last_profile": self.current_active_profile}
            with open(self.SETTINGS_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Failed to save app settings: {e}")

    def load_startup_settings(self):
        """ Loads the last used profile on app launch, or creates Default if none exist """
        
        # 1. Check for existing profiles. If none, create a Default profile.
        try:
            existing_profiles = [f for f in os.listdir(self.PROFILES_DIR) if f.endswith(".json")]
            if not existing_profiles:
                logger.info("No profiles found (First Run). Creating 'Default' profile.")
                default_name = "Default"
                filename = os.path.join(self.PROFILES_DIR, f"{default_name}.json")
                
                # Use current UI values (which are defaults initialized in init)
                data = self.get_current_profile_data()
                
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=2)
                
                self.refresh_profiles()
                self.profile_combo.set(default_name)
                self.load_profile() # This loads it, applies it, and saves it as "last used"
                return
        except Exception as e:
            logger.error(f"Failed to ensure default profile: {e}")

        # 2. Normal startup: Try to load the last used profile
        if not os.path.exists(self.SETTINGS_FILE):
            return

        try:
            with open(self.SETTINGS_FILE, 'r') as f:
                data = json.load(f)
            
            last_profile = data.get("last_profile")
            if last_profile:
                # Verify file still exists
                if os.path.exists(os.path.join(self.PROFILES_DIR, f"{last_profile}.json")):
                    self.profile_combo.set(last_profile)
                    self.load_profile()
        except Exception as e:
            logger.warning(f"Failed to load startup settings: {e}")

    # --- ABOUT TAB ---
    def create_about_tab(self):
        tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=30)
        img_frame = ttk.Frame(tab, style="Card.TFrame")
        img_frame.pack(fill="x", pady=(0, 30))
        try:
            image_path = resource_path("fabPedal.png")
            if HAS_PILLOW:
                pil_img = Image.open(image_path)
                MAX_HEIGHT = 300
                width, height = pil_img.size
                if height > MAX_HEIGHT:
                    ratio = MAX_HEIGHT / height
                    new_width = int(width * ratio)
                    new_height = MAX_HEIGHT
                    pil_img = pil_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                self.product_photo = ImageTk.PhotoImage(pil_img)
            else:
                self.product_photo = tk.PhotoImage(file=image_path)
            lbl_img = tk.Label(img_frame, image=self.product_photo, bg=self.CARD_BG)
            lbl_img.pack(anchor="center")
        except Exception:
            placeholder_bg = "#404040" if self.is_dark_mode else "#f0f0f0"
            placeholder_fg = "#aaaaaa" if self.is_dark_mode else "#888888"
            placeholder = tk.Canvas(img_frame, height=300, bg=placeholder_bg, highlightthickness=0)
            placeholder.pack(fill="x")
            placeholder.create_text(350, 150, text="[ fabPedal.png ]", fill=placeholder_fg, font=(self.FONT_FAMILY, 14, "bold"))

        links_frame = ttk.LabelFrame(tab, text="Follow the Project", style="Card.TLabelframe", padding=20)
        links_frame.pack(fill="x", pady=10)

        def open_url(url):
            webbrowser.open(url)

        def add_link(parent, icon_char, bg_col, text, url):
            row = tk.Frame(parent, bg=self.CARD_BG)
            row.pack(fill="x", pady=8)
            lbl_icon = tk.Label(row, text=icon_char, bg=bg_col, fg="white", width=4, height=1, font=("Segoe UI", 10, "bold"))
            lbl_icon.pack(side="left", padx=(0, 15))
            lbl_text = tk.Label(row, text=text, bg=self.CARD_BG, fg=self.PRIMARY_COLOR, font=(self.FONT_FAMILY, 11, "underline"), cursor="hand2")
            lbl_text.pack(side="left")
            lbl_icon.bind("<Button-1>", lambda e: open_url(url))
            lbl_text.bind("<Button-1>", lambda e: open_url(url))

        add_link(links_frame, "WEB", "#333333", "fabemit.com", "https://fabemit.com")
        add_link(links_frame, "IG", "#E1306C", "Instagram (@fabemit)", "https://instagram.com/fabemitdesign")
        add_link(links_frame, "TT", "#000000", "TikTok (@fabemit)", "https://tiktok.com/@fabemit")
        add_link(links_frame, "YT", "#FF0000", "YouTube Channel", "https://youtube.com/@fabemit")
        add_link(links_frame, "GIT", "#6e5494", "GitHub Repository", "https://github.com/fabemit/fabPedals")

        footer = tk.Frame(tab, bg=self.CARD_BG)
        footer.pack(fill="x", pady=40)
        tk.Label(footer, text=f"fabemit Pedal Manager v{APP_VERSION}", font=(self.FONT_FAMILY, 12, "bold"), bg=self.CARD_BG, fg=self.TEXT_COLOR).pack()
        tk.Label(footer, text="© 2023 fabemit. All rights reserved.", font=(self.FONT_FAMILY, 9), bg=self.CARD_BG, fg="#888").pack()
        return tab
    
    def create_help_tab(self):
        tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=30)
        help_text_1 = """How to Calibrate Your Pedals:

1. Connect your pedals via USB and select the correct COM port.
2. Click 'Connect'. Wait for the connection status to turn green.
3. Go to the tab for the pedal you want to calibrate (Throttle, Brake, or Clutch).
4. Use the 'Wizard' button for step-by-step calibration with auto-smoothing.
5. Click 'Apply Config' to save these settings to the pedal temporarily.
"""
        help_text_2 = """Using Profiles:

1. Once your pedals are calibrated and tuned to your liking, go to the 'Profiles' section.
2. Click 'Save As...' to create a new profile (e.g., 'GT3 Setup').
3. To load a different setup, select it from the dropdown list and click 'Load'.
4. The 'Delete' button removes the selected profile file.
5. CHANGES AUTO-SAVE: When you click "Apply Config" on any pedal or "Save to Memory", your active profile is automatically updated!
"""
        frame1 = ttk.LabelFrame(tab, text="Calibration Guide", style="Card.TLabelframe", padding=20)
        frame1.pack(fill="x", pady=(0, 20))
        lbl_1 = tk.Label(frame1, text=help_text_1, justify="left", bg=self.CARD_BG, fg=self.TEXT_COLOR, font=(self.FONT_FAMILY, 10))
        lbl_1.pack(anchor="w")
        frame2 = ttk.LabelFrame(tab, text="Profile Management", style="Card.TLabelframe", padding=20)
        frame2.pack(fill="x")
        lbl_2 = tk.Label(frame2, text=help_text_2, justify="left", bg=self.CARD_BG, fg=self.TEXT_COLOR, font=(self.FONT_FAMILY, 10))
        lbl_2.pack(anchor="w")
        return tab

    def create_pedal_tab(self, name, prefix):
        tab_bg = ttk.Frame(self.notebook, padding=15)
        
        # Re-bind variables if they don't exist
        if not hasattr(self, f"var_{prefix}_min"):
            setattr(self, f"var_{prefix}_min", tk.IntVar(value=0))
            setattr(self, f"var_{prefix}_max", tk.IntVar(value=1023))
            setattr(self, f"var_{prefix}_curve", tk.DoubleVar(value=1.0))
            setattr(self, f"var_{prefix}_dz_bot", tk.IntVar(value=5))
            setattr(self, f"var_{prefix}_dz_top", tk.IntVar(value=5))
            setattr(self, f"var_{prefix}_curve_mode", tk.IntVar(value=0)) # 0=Gamma, 1=Custom

        
        if prefix == "B" and not hasattr(self, "var_sensor_rating"):
            self.var_sensor_rating = tk.IntVar(value=200)
            self.var_calib_force = tk.IntVar(value=65)
            self.peak_force_session = 0.0

        tab_bg.columnconfigure(0, weight=1)
        tab_bg.columnconfigure(1, weight=1)

        # Left Column
        left_col = ttk.Frame(tab_bg)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 15))

        cal_card = ttk.LabelFrame(left_col, text="Calibration", style="Card.TLabelframe", padding=20)
        cal_card.pack(fill="x", pady=(0, 20))
        
        # --- WIZARD BUTTON ---
        btn_wizard = tk.Button(cal_card, text="🪄 Open Calibration Wizard", 
                               bg=self.PRIMARY_COLOR, fg="white", 
                               font=(self.FONT_FAMILY, 10, "bold"),
                               relief="flat", pady=5,
                               command=lambda: CalibrationWizard(self, name, prefix))
        btn_wizard.pack(fill="x", padx=10, pady=(0, 15))
        # ---------------------
        
        row_min = ttk.Frame(cal_card, style="Card.TFrame")
        row_min.pack(fill="x", pady=8)
        ttk.Label(row_min, text="Min Value:", style="Card.TLabel", width=12).pack(side="left")
        e_min = tk.Entry(row_min, textvariable=getattr(self, f"var_{prefix}_min"), width=8, font=(self.FONT_FAMILY, 10), bg=self.ENTRY_BG, fg=self.ENTRY_FG, insertbackground=self.TEXT_COLOR)
        e_min.pack(side="left", padx=5)
        ttk.Button(row_min, text="Set", width=5, command=lambda: self.set_from_live(prefix, "MIN")).pack(side="left", padx=10)

        row_max = ttk.Frame(cal_card, style="Card.TFrame")
        row_max.pack(fill="x", pady=8)
        ttk.Label(row_max, text="Max Value:", style="Card.TLabel", width=12).pack(side="left")
        e_max = tk.Entry(row_max, textvariable=getattr(self, f"var_{prefix}_max"), width=8, font=(self.FONT_FAMILY, 10), bg=self.ENTRY_BG, fg=self.ENTRY_FG, insertbackground=self.TEXT_COLOR)
        e_max.pack(side="left", padx=5)
        ttk.Button(row_max, text="Set", width=5, command=lambda: self.set_from_live(prefix, "MAX")).pack(side="left", padx=10)

        dz_card = ttk.LabelFrame(left_col, text="Deadzones", style="Card.TLabelframe", padding=20)
        dz_card.pack(fill="x", pady=(0, 20))
        
        row_dz = ttk.Frame(dz_card, style="Card.TFrame")
        row_dz.pack(fill="x", pady=5)
        ttk.Label(row_dz, text="Bottom (%):", style="Card.TLabel").pack(side="left")
        e_dzb = tk.Entry(row_dz, textvariable=getattr(self, f"var_{prefix}_dz_bot"), width=5, font=(self.FONT_FAMILY, 10), bg=self.ENTRY_BG, fg=self.ENTRY_FG, insertbackground=self.TEXT_COLOR)
        e_dzb.pack(side="left", padx=(5, 20))
        e_dzb.bind('<KeyRelease>', lambda e: self.draw_curve(prefix)) 
        ttk.Label(row_dz, text="Top (%):", style="Card.TLabel").pack(side="left")
        e_dzt = tk.Entry(row_dz, textvariable=getattr(self, f"var_{prefix}_dz_top"), width=5, font=(self.FONT_FAMILY, 10), bg=self.ENTRY_BG, fg=self.ENTRY_FG, insertbackground=self.TEXT_COLOR)
        e_dzt.pack(side="left", padx=5)
        e_dzt.bind('<KeyRelease>', lambda e: self.draw_curve(prefix))

        crv_card = ttk.LabelFrame(left_col, text="Response Curve", style="Card.TLabelframe", padding=20)
        crv_card.pack(fill="x")

        # --- MODE TOGGLE ---
        mode_frame = ttk.Frame(crv_card, style="Card.TFrame")
        mode_frame.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(mode_frame, text="Simple Gamma", variable=getattr(self, f"var_{prefix}_curve_mode"), value=0, command=lambda: self.on_curve_mode_change(prefix)).pack(side="left", padx=(0,15))
        ttk.Radiobutton(mode_frame, text="Custom Points", variable=getattr(self, f"var_{prefix}_curve_mode"), value=1, command=lambda: self.on_curve_mode_change(prefix)).pack(side="left")

        # --- SLIDER CONTAINER ---
        slider_frame = ttk.Frame(crv_card, style="Card.TFrame")
        slider_frame.pack(fill="x")
        setattr(self, f"frame_slider_{prefix}", slider_frame)

        lbl_curve = ttk.Label(slider_frame, text="Gamma: 1.00", style="Card.TLabel", font=(self.FONT_FAMILY, 14, "bold"), foreground=self.PRIMARY_COLOR)
        lbl_curve.pack(anchor="w")
        setattr(self, f"lbl_curve_{prefix}", lbl_curve)
        
        scale = ttk.Scale(slider_frame, from_=0.5, to=3.0, variable=getattr(self, f"var_{prefix}_curve"), orient="horizontal")
        scale.pack(fill="x", pady=(15, 10))
        
        def reset_curve():
            if getattr(self, f"var_{prefix}_curve_mode").get() == 0:
                getattr(self, f"var_{prefix}_curve").set(1.0)
                lbl_curve.config(text="Gamma: 1.00")
            else:
                self.custom_curves[prefix] = [10, 20, 30, 40, 50, 60, 70, 80, 90]
            self.draw_curve(prefix)
            
        ttk.Button(slider_frame, text="Reset to Linear", command=reset_curve).pack(anchor="e")
        
        # We also need a "Reset" button for custom mode that sits outside the slider frame
        self.btn_reset_custom = ttk.Button(crv_card, text="Reset to Linear", command=reset_curve)
        
        def on_slide(v):
            lbl_curve.config(text=f"Gamma: {float(v):.2f}")
            self.draw_curve(prefix)
        scale.configure(command=on_slide)

        # Right Column
        right_col = ttk.Frame(tab_bg)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(15, 0))

        graph_card = ttk.LabelFrame(right_col, text="Visualizer", style="Card.TLabelframe", padding=20)
        graph_card.pack(fill="x", pady=(0, 20))
        canvas = tk.Canvas(graph_card, width=300, height=200, bg=self.CARD_BG, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        setattr(self, f"canvas_{prefix}", canvas)
        
        # BIND CANVAS EVENTS FOR DRAGGING
        canvas.bind("<ButtonPress-1>", lambda e, p=prefix: self.on_canvas_click(e, p))
        canvas.bind("<B1-Motion>", lambda e, p=prefix: self.on_canvas_drag(e, p))
        canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        live_card = ttk.LabelFrame(right_col, text="Live Output", style="Card.TLabelframe", padding=20)
        live_card.pack(fill="x")
        ttk.Label(live_card, text="Raw Input", style="Card.TLabel").pack(anchor="w")
        setattr(self, f"bar_{prefix}_raw", ttk.Progressbar(live_card, maximum=1023, style="Horizontal.TProgressbar"))
        getattr(self, f"bar_{prefix}_raw").pack(fill="x", pady=(5, 15))
        ttk.Label(live_card, text="Game Output", style="Card.TLabel").pack(anchor="w")
        setattr(self, f"bar_{prefix}_out", ttk.Progressbar(live_card, maximum=1023, style="Horizontal.TProgressbar"))
        getattr(self, f"bar_{prefix}_out").pack(fill="x", pady=(5, 10))
        setattr(self, f"live_{prefix}_val", 0)

        if prefix == "B":
            force_card = ttk.LabelFrame(right_col, text="Force Calculator", style="Card.TLabelframe", padding=20)
            force_card.pack(fill="x", pady=20)
            f_row = ttk.Frame(force_card, style="Card.TFrame")
            f_row.pack(fill="x", pady=(0, 10))
            ttk.Label(f_row, text="Sensor (kg):", style="Card.TLabel").pack(side="left")
            tk.Entry(f_row, textvariable=self.var_sensor_rating, width=5, font=(self.FONT_FAMILY, 10), bg=self.ENTRY_BG, fg=self.ENTRY_FG, insertbackground=self.TEXT_COLOR).pack(side="left", padx=5)
            ttk.Label(f_row, text="Calib Force (kg):", style="Card.TLabel").pack(side="left", padx=(15,0))
            tk.Entry(f_row, textvariable=self.var_calib_force, width=5, font=(self.FONT_FAMILY, 10), bg=self.ENTRY_BG, fg=self.ENTRY_FG, insertbackground=self.TEXT_COLOR).pack(side="left", padx=5)
            self.lbl_live_force = tk.Label(force_card, text="0.0 kg", font=(self.FONT_FAMILY, 28, "bold"), fg=self.PRIMARY_COLOR, bg=self.CARD_BG)
            self.lbl_live_force.pack(anchor="center", pady=5)
            peak_fg = "#888" if not self.is_dark_mode else "#aaaaaa"
            self.lbl_peak_force = tk.Label(force_card, text="Peak: 0.0 kg", font=(self.FONT_FAMILY, 10), bg=self.CARD_BG, fg=peak_fg)
            self.lbl_peak_force.pack(anchor="center")

        ttk.Button(right_col, text=f"APPLY {name.upper()} CONFIG", style="Primary.TButton", command=lambda: self.send_pedal_update(prefix)).pack(fill="x", pady=(20, 0))
        
        # Initial UI State
        self.root.after(100, lambda: self.on_curve_mode_change(prefix))

        return tab_bg

    def on_curve_mode_change(self, prefix):
        mode = getattr(self, f"var_{prefix}_curve_mode").get()
        slider_frame = getattr(self, f"frame_slider_{prefix}")
        
        if mode == 0: # Gamma
            slider_frame.pack(fill="x")
            self.btn_reset_custom.pack_forget()
        else: # Custom
            slider_frame.pack_forget()
            self.btn_reset_custom.pack(anchor="e", pady=10)
            
        self.draw_curve(prefix)

    def update_brake_force_display(self, raw_val):
        try:
            b_min = self.var_B_min.get()
            b_max = self.var_B_max.get()
            force_at_max = self.var_calib_force.get()
            if b_max == b_min: return 
            pct = (raw_val - b_min) / (b_max - b_min)
            if pct < 0: pct = 0
            current_kg = pct * force_at_max
            if current_kg > self.peak_force_session:
                self.peak_force_session = current_kg
            self.lbl_live_force.config(text=f"{current_kg:.1f} kg")
            self.lbl_peak_force.config(text=f"Peak: {self.peak_force_session:.1f} kg")
        except:
            pass

    # --- CANVAS INTERACTIONS ---
    def on_canvas_click(self, event, prefix):
        mode = getattr(self, f"var_{prefix}_curve_mode").get()
        if mode != 1: return # Only custom mode
        
        canvas = getattr(self, f"canvas_{prefix}")
        x, y = event.x, event.y
        
        # Find closest point handle
        closest = canvas.find_closest(x, y)
        tags = canvas.gettags(closest)
        
        if "handle" in tags:
            # Extract index from tag "handle_X"
            for tag in tags:
                if tag.startswith("handle_"):
                    idx = int(tag.split("_")[1])
                    self.drag_data = {"active": True, "prefix": prefix, "index": idx}
                    break

    def on_canvas_drag(self, event, prefix):
        if not self.drag_data["active"]: return
        if self.drag_data["prefix"] != prefix: return
        
        idx = self.drag_data["index"]
        canvas = getattr(self, f"canvas_{prefix}")
        h = canvas.winfo_height()
        
        # Calc new Y percentage (inverted)
        new_y_px = max(0, min(h, event.y))
        new_val = 100 - (new_y_px / h * 100)
        
        # Update data
        self.custom_curves[prefix][idx] = int(new_val)
        
        # Redraw
        self.draw_curve(prefix)
        
    def on_canvas_release(self, event):
        self.drag_data = {"active": False, "prefix": None, "index": -1}
        # Trigger autosave logic if we just finished dragging? 
        # Ideally we don't spam saves, so maybe just leave it for "Apply Config"

    def draw_curve(self, prefix):
        canvas = getattr(self, f"canvas_{prefix}")
        mode = getattr(self, f"var_{prefix}_curve_mode").get()
        
        try:
            dz_bot = getattr(self, f"var_{prefix}_dz_bot").get()
            dz_top = getattr(self, f"var_{prefix}_dz_top").get()
        except:
            dz_bot, dz_top = 5, 5

        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10: w, h = 300, 200

        grid_color = "#e0e0e0" if not self.is_dark_mode else "#444444"
        canvas.create_line(0, h, w, h, fill=grid_color, width=2) 
        canvas.create_line(0, 0, 0, h, fill=grid_color, width=2) 
        
        # Draw Deadzones
        dz_color = "#fff5f5" if not self.is_dark_mode else "#3a2a2a"
        bot_pixel_width = (dz_bot / 100.0) * w
        canvas.create_rectangle(0, 0, bot_pixel_width, h, fill=self.DZ_FILL, outline=self.DZ_LINE)
        
        top_pixel_width = (dz_top / 100.0) * w
        canvas.create_rectangle(w - top_pixel_width, 0, w, h, fill=self.DZ_FILL, outline=self.DZ_LINE)

        # Draw Curve
        points = []
        
        if mode == 0:
            # GAMMA MODE
            curve = getattr(self, f"var_{prefix}_curve").get()
            for x in range(w):
                input_pct = x / float(w)
                dz_bot_pct = dz_bot / 100.0
                dz_top_pct = dz_top / 100.0
                
                if input_pct <= dz_bot_pct:
                    val = 0.0
                elif input_pct >= (1.0 - dz_top_pct):
                    val = 1.0
                else:
                    active_range = 1.0 - dz_bot_pct - dz_top_pct
                    if active_range <= 0: val = 0.0 
                    else: val = (input_pct - dz_bot_pct) / active_range
                
                val = math.pow(val, curve)
                y = h - (val * h)
                points.append(x)
                points.append(y)
            canvas.create_line(points, fill=self.PRIMARY_COLOR, width=3, smooth=True)
            
        else:
            # CUSTOM POINTS MODE
            # We map the custom points to the ACTIVE range (between deadzones)
            active_w = w - bot_pixel_width - top_pixel_width
            start_x = bot_pixel_width
            
            # Start Point (0,0 relative to active area)
            points_to_draw = [(start_x, h)] 
            
            custom_vals = self.custom_curves[prefix] # 9 values
            
            # Draw intermediate points
            for i, val in enumerate(custom_vals):
                # i=0 is 10%, i=8 is 90%
                pct = (i + 1) * 10 / 100.0
                px = start_x + (active_w * pct)
                py = h - (val / 100.0 * h)
                points_to_draw.append((px, py))
                
                # Draw interactive handle
                r = 6
                fill_col = "white" if self.drag_data["index"] == i and self.drag_data["prefix"] == prefix else self.PRIMARY_COLOR
                canvas.create_oval(px-r, py-r, px+r, py+r, fill=fill_col, outline="white", width=2, tags=("handle", f"handle_{i}"))

            # End Point (100, 100 relative to active area)
            points_to_draw.append((w - top_pixel_width, 0))
            
            # Add deadzone extensions
            if bot_pixel_width > 0:
                points_to_draw.insert(0, (0, h))
            if top_pixel_width > 0:
                points_to_draw.append((w, 0))
                
            # Flatten list for create_line
            flat_pts = [coord for pt in points_to_draw for coord in pt]
            canvas.create_line(flat_pts, fill=self.PRIMARY_COLOR, width=3)


    def redraw_all_graphs(self):
        self.draw_curve("T")
        self.draw_curve("B")
        self.draw_curve("C")

    def refresh_ports(self):
        try:
            ports = [port.device for port in serial.tools.list_ports.comports()]
            self.port_combo['values'] = ports
            if ports: self.port_combo.current(0)
        except Exception:
            logger.exception("refresh_ports failed")

    def safe_serial_write(self, data: bytes):
        try:
            if self.ser and self.is_connected:
                self.ser.write(data)
        except Exception:
            logger.exception("safe_serial_write failed")

    def toggle_connection(self):
        if not self.is_connected:
            try:
                port = self.port_combo.get()
                if not port:
                    messagebox.showerror("Error", "No port selected.")
                    return
                self.ser = serial.Serial(port, 9600, timeout=1)
                self.is_connected = True
                self.btn_connect.config(text="Disconnect")
                self.lbl_status.config(text="🟢 Connected", fg="#28a745")
                self.update_ui_state() # Update UI to unlocked state
                
                # schedule a couple of initial commands without blocking UI
                self.root.after(200, lambda: self.safe_serial_write(b"READ\n"))
                self.root.after(400, lambda: self.safe_serial_write(b"DEBUG_ON\n"))
            except Exception as e:
                logger.exception("toggle_connection failed")
                messagebox.showerror("Error", str(e))
                self.lbl_status.config(text="⚠️ Connection Failed", fg="#dc3545")
        else:
            try:
                self.safe_serial_write(b"DEBUG_OFF\n")
                try:
                    self.ser.close()
                except Exception:
                    pass
            except Exception:
                logger.exception("toggle_connection disconnect failed")
            self.is_connected = False
            self.btn_connect.config(text="Connect")
            self.lbl_status.config(text="🔴 Not Connected", fg="#dc3545")
            self.update_ui_state() # Update UI to locked state

    def serial_loop(self):
        while self.running:
            if self.is_connected and self.ser:
                try:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        if not line:
                            continue
                        if line.startswith("LIVE:"):
                            # schedule parse on main thread
                            try:
                                self.root.after(0, lambda l=line: self.parse_live(l))
                            except Exception:
                                # fallback to direct call if scheduling fails
                                self.parse_live(line)
                        elif line.startswith("CONF:") or line.startswith("CONF"):
                            try:
                                self.root.after(0, lambda l=line: self.parse_config(l))
                            except Exception:
                                self.parse_config(line)
                except Exception:
                    logger.exception("Error in serial_loop")
            time.sleep(0.01)

    def parse_live(self, line):
        try:
            parts = line.split(':')
            if len(parts) >= 7:
                t_raw = int(parts[1])
                t_out = int(parts[2])
                c_raw = int(parts[3])
                c_out = int(parts[4])
                b_raw = int(parts[5])
                b_out = int(parts[6])

                self.live_T_val = t_raw
                self.live_C_val = c_raw
                self.live_B_val = b_raw

                # clamp values for Throttle and Clutch (standard pots usually 0-1023)
                self.bar_T_raw['value'] = max(0, min(1023, t_raw))
                self.bar_T_out['value'] = max(0, min(1023, t_out))
                self.bar_C_raw['value'] = max(0, min(1023, c_raw))
                self.bar_C_out['value'] = max(0, min(1023, c_out))
                
                # --- BRAKE BAR SCALING FIX ---
                # Dynamically adjust the raw bar maximum to accommodate load cells
                # (which might go way above 1023) or sensitive calibrations.
                b_calib_max = self.var_B_max.get()
                
                # Ensure the bar can display the full range of the calibration
                # plus a little headroom, or expand if the raw value goes higher.
                # Default to 1023 minimum to prevent tiny bars on startup.
                target_max = max(1023, int(b_calib_max * 1.1), b_raw)
                
                # Only re-configure if there's a significant change to avoid UI flicker
                if abs(self.bar_B_raw['maximum'] - target_max) > 5:
                    self.bar_B_raw.configure(maximum=target_max)

                self.bar_B_raw['value'] = b_raw
                self.bar_B_out['value'] = max(0, min(1023, b_out))

                self.update_brake_force_display(b_raw)
        except Exception:
            logger.exception("parse_live failed for line: %s", line)

    def parse_config(self, line):
        try:
            p = line.split(':')
            if len(p) >= 16:
                # convert and set safely
                try:
                    self.var_T_min.set(int(p[1]))
                    self.var_T_max.set(int(p[2]))
                    self.var_C_min.set(int(p[3]))
                    self.var_C_max.set(int(p[4]))
                    self.var_B_min.set(int(p[5]))
                    self.var_B_max.set(int(p[6]))

                    self.var_T_dz_bot.set(int(p[7])); self.var_T_dz_top.set(int(p[8]))
                    self.var_C_dz_bot.set(int(p[9])); self.var_C_dz_top.set(int(p[10]))
                    self.var_B_dz_bot.set(int(p[11])); self.var_B_dz_top.set(int(p[12]))

                    self.var_T_curve.set(float(p[13]))
                    self.var_C_curve.set(float(p[14]))
                    self.var_B_curve.set(float(p[15]))
                except Exception:
                    logger.exception("parse_config conversion failed")

                # update labels
                lbl_t = getattr(self, "lbl_curve_T", None)
                if lbl_t: lbl_t.config(text=f"Gamma: {float(p[13]):.2f}")
                
                lbl_c = getattr(self, "lbl_curve_C", None)
                if lbl_c: lbl_c.config(text=f"Gamma: {float(p[14]):.2f}")
                
                lbl_b = getattr(self, "lbl_curve_B", None)
                if lbl_b: lbl_b.config(text=f"Gamma: {float(p[15]):.2f}")
                
                self.root.after(100, self.redraw_all_graphs)
        except Exception:
            logger.exception("parse_config failed for line: %s", line)

    def send_pedal_update(self, prefix):
        if not self.is_connected: return
        try:
            # Reset peak force if updating Brake settings
            if prefix == "B":
                self.peak_force_session = 0.0
                if hasattr(self, "lbl_peak_force"):
                    self.lbl_peak_force.config(text="Peak: 0.0 kg")

            mn = getattr(self, f"var_{prefix}_min").get()
            mx = getattr(self, f"var_{prefix}_max").get()
            crv = getattr(self, f"var_{prefix}_curve").get()
            dzb = getattr(self, f"var_{prefix}_dz_bot").get()
            dzt = getattr(self, f"var_{prefix}_dz_top").get()
            
            self.safe_serial_write(f"SET:{prefix}MIN:{mn}\n".encode())
            self.safe_serial_write(f"SET:{prefix}MAX:{mx}\n".encode())
            self.safe_serial_write(f"SET:{prefix}CRV:{crv}\n".encode())
            self.safe_serial_write(f"SET:{prefix}DZBOT:{dzb}\n".encode())
            self.safe_serial_write(f"SET:{prefix}DZTOP:{dzt}\n".encode())
            
            # NOTE: If the firmware supports custom LUT/Points, you would send them here.
            # For now, this just updates the UI side and standard params.
            mode = getattr(self, f"var_{prefix}_curve_mode").get()
            if mode == 1:
                # Example: If firmware supports it: SET:TCUST:10,20,35...
                pts_str = ",".join(map(str, self.custom_curves[prefix]))
                logger.info(f"Would send custom points for {prefix}: {pts_str}")
            
            # AUTO SAVE TRIGGER
            self.auto_save_current_profile()
            
        except Exception:
            logger.exception("send_pedal_update failed for %s", prefix)

    def set_from_live(self, prefix, target):
        val = getattr(self, f"live_{prefix}_val")
        try:
            getattr(self, f"var_{prefix}_{target.lower()}").set(val)
        except Exception:
            logger.exception("set_from_live failed")

    def save_to_eeprom(self):
        if self.is_connected:
            # apply all settings without blocking UI
            def apply_and_save():
                try:
                    self.send_pedal_update("T")
                    time.sleep(0.05)
                    self.send_pedal_update("B")
                    time.sleep(0.05)
                    self.send_pedal_update("C")
                    time.sleep(0.05)
                    self.safe_serial_write(b"SAVE\n")
                    # notify on main thread
                    self.root.after(0, lambda: messagebox.showinfo("Success", "All current settings applied and saved to Pedal Memory!"))
                    
                    # AUTO SAVE TRIGGER
                    self.root.after(0, self.auto_save_current_profile)
                    
                except Exception:
                    logger.exception("save_to_eeprom failed")
            threading.Thread(target=apply_and_save, daemon=True).start()

    def on_close(self):
        # stop thread and close serial safely
        try:
            self.running = False
            try:
                if self.ser and getattr(self.ser, "is_open", False):
                    try:
                        self.safe_serial_write(b"DEBUG_OFF\n")
                    except Exception:
                        pass
                    try:
                        self.ser.close()
                    except Exception:
                        pass
            except Exception:
                logger.exception("on_close serial shutdown failed")
            # allow thread to exit gracefully
            try:
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=0.5)
            except Exception:
                pass
        finally:
            try:
                self.root.destroy()
            except Exception:
                pass

if __name__ == "__main__":
    root = tk.Tk()
    app = PedalApp(root)
    root.update()
    app.redraw_all_graphs()
    root.mainloop()