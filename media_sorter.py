import shutil, hashlib, threading, traceback, time, json, re, webbrowser, subprocess, sys, os
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

# ── 1. SECURITY & CONFIGURATION ──────────────────────────────────────────────
# Default password: admin
PASSWORD_HASH = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"
APP_VERSION = "Version 1"

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.heic'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v'}
HISTORY_FILE = Path(".sorter_history.json")

def check_features():
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    results = {}
    try:
        import exifread
        results["exif"] = (True, "Ready", "https://pypi.org")
    except: results["exif"] = (False, "Missing", "https://pypi.org")
    try:
        from geopy.geocoders import Nominatim
        results["geopy"] = (True, "Ready", "https://readthedocs.io")
    except: results["geopy"] = (False, "Missing", "https://readthedocs.io")
    return results

STATUS = check_features()

# ── 2. LOGIC HELPERS ─────────────────────────────────────────────────────────
def file_md5(path: Path) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
    except OSError: return "corrupted"
    return h.hexdigest()

def sanitize_name(name: str):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def get_gps_location(path: Path):
    if not STATUS["exif"]: return None
    try:
        import exifread
        with open(path, 'rb') as f:
            tags = exifread.process_file(f, details=False)
        def _to_decimal(values, ref):
            d, m, s = [float(v.num)/float(v.den) for v in values]
            val = d + (m/60.0) + (s/3600.0)
            return -val if ref in ['S', 'W'] else val
        lat, lat_ref = tags.get('GPS GPSLatitude'), tags.get('GPS GPSLatitudeRef')
        lon, lon_ref = tags.get('GPS GPSLongitude'), tags.get('GPS GPSLongitudeRef')
        if lat and lon: return _to_decimal(lat.values, lat_ref.values), _to_decimal(lon.values, lon_ref.values)
    except: pass
    return None

def reverse_geocode_details(lat, lon):
    if not STATUS["geopy"]: return "Unknown", "Unknown"
    try:
        from geopy.geocoders import Nominatim
        geo = Nominatim(user_agent="media_sorter_v1")
        loc = geo.reverse((lat, lon), language='en', timeout=10)
        addr = loc.raw.get('address', {})
        return addr.get('country', 'Unknown'), addr.get('city') or addr.get('town') or 'Unknown'
    except: return "Unknown", "Unknown"

# ── 3. MAIN APPLICATION ───────────────────────────────────────────────────────
class MediaSorterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Media Sorter Pro - {APP_VERSION}")
        self.geometry("1000x980")
        self.configure(bg="#c8cde0")

        # Variables
        self.progress_val, self.import_folder, self.save_folder = tk.DoubleVar(), tk.StringVar(), tk.StringVar()
        self.custom_prefix, self.status_text = tk.StringVar(value=""), tk.StringVar(value="System Ready")
        self.opt_sort_geo = tk.BooleanVar(value=STATUS["geopy"])
        self.opt_rename = tk.BooleanVar(value=True)
        self.opt_transfer_mode = tk.StringVar(value="Copy")
        self.opt_filter_logs = tk.BooleanVar(value=False)

        self._build_ui()

    def _build_ui(self):
        BG, PANEL, ACCENT, GREEN = "#c8cde0", "#d8dcea", "#4f46e5", "#15803d"
        tk.Label(self, text=f"◈ MEDIA SORTER PRO - {APP_VERSION}", bg=BG, fg=ACCENT, font=("Segoe UI", 16, "bold")).pack(pady=15)

        # Paths Panel
        path_f = tk.LabelFrame(self, text=" Paths ", bg=PANEL, font=("Segoe UI", 9, "bold")); path_f.pack(fill="x", padx=20, pady=5)
        self._path_row(path_f, "SOURCE:", self.import_folder, self._browse_import, PANEL, BG, ACCENT)
        self._path_row(path_f, "DESTINATION:", self.save_folder, self._browse_save, PANEL, BG, ACCENT)

        # Options Panel
        opts_f = tk.LabelFrame(self, text=" Task Options ", bg=PANEL, font=("Segoe UI", 9, "bold")); opts_f.pack(fill="x", padx=20, pady=5)
        tk.Checkbutton(opts_f, text="Geo-Sort (Location)", variable=self.opt_sort_geo, bg=PANEL).grid(row=0, column=0, padx=10, pady=5)
        tk.Checkbutton(opts_f, text="Rename (Date-Location)", variable=self.opt_rename, bg=PANEL).grid(row=0, column=1, padx=10)
        tk.Radiobutton(opts_f, text="Copy (Safe)", variable=self.opt_transfer_mode, value="Copy", bg=PANEL).grid(row=0, column=2, padx=10)
        tk.Radiobutton(opts_f, text="Move (Clear Source)", variable=self.opt_transfer_mode, value="Move", bg=PANEL, fg="#b91c1c").grid(row=0, column=3, padx=10)

        # Main Button Row
        btn_f = tk.Frame(self, bg=BG); btn_f.pack(fill="x", padx=20, pady=10)
        tk.Button(btn_f, text="▶ START SORTING", command=self.start_sorting, bg=GREEN, fg="white", font=("Segoe UI", 10, "bold"), width=20, pady=10).pack(side="left", expand=True)
        tk.Button(btn_f, text="↺ UNDO", command=self.undo_last, bg="#b45309", fg="white", font=("Segoe UI", 9, "bold"), width=10, pady=10).pack(side="left", padx=2)
        tk.Button(btn_f, text="🔧 REPAIR", command=self.repair_index, bg=ACCENT, fg="white", font=("Segoe UI", 9, "bold"), width=10, pady=10).pack(side="left", padx=2)
        tk.Button(btn_f, text="⚙ SETUP", command=self.show_settings, bg="#4f46e5", fg="white", font=("Segoe UI", 9, "bold"), width=10, pady=10).pack(side="left", padx=2)

        # Progress & Log Area
        ttk.Progressbar(self, variable=self.progress_val, maximum=100).pack(fill="x", padx=20, pady=5)
        
        log_ctrl = tk.Frame(self, bg=BG); log_ctrl.pack(fill="x", padx=20)
        tk.Label(log_ctrl, text="ACTIVITY LOG", bg=BG, font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(log_ctrl, text="💾 EXPORT", command=self.export_log, font=("Segoe UI", 7), bg="white").pack(side="right", padx=2)
        tk.Button(log_ctrl, text="🗑️ CLEAR", command=self.clear_log, font=("Segoe UI", 7), bg="white").pack(side="right", padx=2)
        tk.Checkbutton(log_ctrl, text="ERRORS ONLY", variable=self.opt_filter_logs, bg=BG, font=("Segoe UI", 7, "bold")).pack(side="right", padx=10)

        self.log_area = scrolledtext.ScrolledText(self, height=18, state='disabled', font=("Consolas", 9), bg="white"); self.log_area.pack(fill="both", expand=True, padx=20, pady=5)
        tk.Label(self, textvariable=self.status_text, bd=1, relief="sunken", anchor="w").pack(side="bottom", fill="x")

    def _path_row(self, p, t, v, cmd, pa, b, a):
        r = tk.Frame(p, bg=pa); r.pack(fill="x", padx=10, pady=5)
        tk.Label(r, text=t, bg=pa, width=12, anchor="w", font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Entry(r, textvariable=v, bg="white").pack(side="left", fill="x", expand=True, padx=5)
        tk.Button(r, text="Browse", command=cmd, bg=a, fg="white", font=("Segoe UI", 8)).pack(side="left")

    def _browse_import(self): p = filedialog.askdirectory(); self.import_folder.set(p); self.log(f"Source set: {p}")
    def _browse_save(self): p = filedialog.askdirectory(); self.save_folder.set(p); self.log(f"Destination set: {p}")

    def log(self, m, l="INFO"):
        if self.opt_filter_logs.get() and l in ["INFO", "SUCCESS"]: return
        def app():
            self.log_area.configure(state='normal')
            color = {"ERROR": "red", "WARNING": "orange", "FAILED": "orange", "SUCCESS": "green"}.get(l, "black")
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.log_area.insert(tk.END, f"[{timestamp}] {l}: {m}\n")
            if color != "black":
                self.log_area.tag_add(l, "end-2c linestart", "end-1c")
                self.log_area.tag_config(l, foreground=color)
            self.log_area.configure(state='disabled'); self.log_area.see(tk.END)
        self.after(0, app)

    def export_log(self):
        content = self.log_area.get("1.0", tk.END)
        if not content.strip(): return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f: f.write(content)
            messagebox.showinfo("Exported", "Log saved successfully.")

    def clear_log(self):
        if messagebox.askyesno("Clear", "Wipe log history?"):
            self.log_area.configure(state='normal'); self.log_area.delete("1.0", tk.END); self.log_area.configure(state='disabled')

    def repair_index(self):
        if messagebox.askyesno("Repair", "Restart Windows Indexer? (Requires Admin)"):
            try:
                subprocess.run(["net", "stop", "WSearch"], capture_output=True, check=False)
                time.sleep(1)
                subprocess.run(["net", "start", "WSearch"], capture_output=True, check=False)
                self.log("Indexer locks released.", "SUCCESS")
            except Exception as e: self.log(f"Repair Error: {e}", "ERROR")

    def show_settings(self):
        sw = tk.Toplevel(self); sw.title("Help & Requirements"); sw.geometry("650x550")
        tk.Label(sw, text="System Requirements", font=("Segoe UI", 12, "bold")).pack(pady=10)
        for lib, (avail, cmd, link) in STATUS.items():
            f = tk.Frame(sw); f.pack(fill="x", padx=20, pady=5)
            tk.Label(f, text=lib.upper(), width=12, fg="green" if avail else "red", font=("Segoe UI", 9, "bold")).pack(side="left")
            tk.Label(f, text=cmd, font=("Consolas", 8), bg="#eee").pack(side="left", padx=10)
            tk.Button(f, text="Docs", command=lambda u=link: webbrowser.open(u), font=("Segoe UI", 8)).pack(side="right")
        
        tk.Label(sw, text="ABOUT MEDIA SORTER PRO", font=("Segoe UI", 10, "bold")).pack(pady=(20, 5))
        txt = scrolledtext.ScrolledText(sw, height=10, font=("Segoe UI", 9)); txt.pack(padx=20, pady=5)
        txt.insert(tk.END, "Professional AI organizer for messy drives.\n- Date & Geo Sorting\n- Duplicate Detection\n- Safe-Scan Technology for corrupted drives.")
        txt.configure(state='disabled')

    def start_sorting(self):
        if not self.import_folder.get() or not self.save_folder.get(): return messagebox.showwarning("Error", "Paths missing.")
        if self.opt_transfer_mode.get() == "Move":
            if not messagebox.askyesno("MOVE WARNING", "Photos will be DELETED from source and empty folders cleared. Proceed?"): return
        threading.Thread(target=self.run_sorting, args=(Path(self.import_folder.get()), Path(self.save_folder.get())), daemon=True).start()

    def run_sorting(self, src, dst):
        try:
            self.status_text.set("Scanning drive (Safe Mode)...")
            all_files = []
            for f in src.rglob('*'):
                try:
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS: all_files.append(f)
                except OSError: continue
            
            total = len(all_files); history, hashes, mode = [], set(), self.opt_transfer_mode.get()
            for i, fpath in enumerate(all_files):
                self.after(0, lambda v=(i/total)*100, n=fpath.name: [self.progress_val.set(v), self.status_text.set(f"Sorting: {n}")])
                try:
                    h = file_md5(fpath)
                    if h == "corrupted": sub, name = "_ManualCheck", fpath.name
                    elif h in hashes: sub, name = "_Duplicates", fpath.name
                    else:
                        hashes.add(h); dt = datetime.fromtimestamp(fpath.stat().st_mtime); sub = dt.strftime("%Y/%Y-%m"); tag = ""
                        if self.opt_sort_geo.get():
                            gps = get_gps_location(fpath)
                            if gps: _, city = reverse_geocode_details(*gps); sub, tag = f"{sub}/{city}", f"-{city}"; time.sleep(1)
                        name = sanitize_name(f"{dt.strftime('%Y-%m-%d')}{tag}-{fpath.name}") if self.opt_rename.get() else fpath.name
                    
                    t_file = dst / sub / name; t_file.parent.mkdir(parents=True, exist_ok=True)
                    if mode == "Move": shutil.move(str(fpath), str(t_file))
                    else: shutil.copy2(str(fpath), str(t_file))
                    history.append({"src": str(fpath), "dst": str(t_file), "mode": mode})
                except Exception as e: self.log(f"Skipped {fpath.name}: {e}", "WARNING")

            if history: HISTORY_FILE.write_text(json.dumps(history))
            if mode == "Move": self.cleanup(src)
            self.status_text.set("Ready"); messagebox.showinfo("Done", f"Task Complete. Processed {len(all_files)} items.")
        except: self.log(traceback.format_exc(), "ERROR")

    def cleanup(self, path):
        for item in path.iterdir():
            if item.is_dir(): self.cleanup(item)
        if path != Path(self.import_folder.get()) and path.is_dir() and not any(path.iterdir()):
            try: path.rmdir()
            except: pass

    def undo_last(self):
        if not HISTORY_FILE.exists() or not messagebox.askyesno("Undo", "Revert last session?"): return
        h = json.loads(HISTORY_FILE.read_text())
        for item in h:
            s, d = Path(item["src"]), Path(item["dst"])
            if item["mode"] == "Move" and d.exists(): s.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(d), str(s))
            elif d.exists(): d.unlink()
        HISTORY_FILE.unlink(); self.log("Undo Complete", "SUCCESS")

# ── 4. SECURITY GATE ─────────────────────────────────────────────────────────
class LoginWindow(tk.Toplevel):
    def __init__(self, on_success):
        super().__init__(); self.on_success = on_success; self.title("Access Control")
        w, h = 300, 150; x = (self.winfo_screenwidth()//2)-(w//2); y = (self.winfo_screenheight()//2)-(h//2)
        self.geometry(f'{w}x{h}+{x}+{y}'); tk.Label(self, text="ENTER SYSTEM PASSWORD:", font=("Segoe UI", 9, "bold")).pack(pady=15)
        self.e = tk.Entry(self, show="*", justify="center"); self.e.pack(padx=20, fill="x")
        self.e.bind("<Return>", lambda e: self.validate()); self.e.focus_set()
        tk.Button(self, text="UNLOCK", command=self.validate, bg="#4f46e5", fg="white").pack(pady=15)

    def validate(self):
        if hashlib.sha256(self.e.get().encode()).hexdigest() == PASSWORD_HASH: self.destroy(); self.on_success()
        else: messagebox.showerror("Denied", "Incorrect Password"); self.e.delete(0, tk.END)

if __name__ == "__main__":
    root = tk.Tk(); root.withdraw()
    def launch(): app = MediaSorterApp(); app.mainloop(); root.destroy()
    LoginWindow(launch); root.mainloop()

