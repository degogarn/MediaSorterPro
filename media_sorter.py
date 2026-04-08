import shutil, hashlib, threading, traceback, time, json, re, webbrowser, subprocess, sys, os
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

# ── 1. Security & Configuration ──────────────────────────────────────────────
# Default password: admin
PASSWORD_HASH = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.heic'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v'}
HISTORY_FILE = Path(".sorter_history.json")
CLASSIFIER = None

def check_features():
    # Suppress AI/HuggingFace warnings on Windows
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
    try:
        from transformers import pipeline
        results["classify"] = (True, "Ready", "https://huggingface.co")
    except: results["classify"] = (False, "Missing", "https://huggingface.co")
    return results

STATUS = check_features()

# ── 2. Logic Helpers ─────────────────────────────────────────────────────────
def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
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
        geo = Nominatim(user_agent="media_sorter_pro_v15")
        loc = geo.reverse((lat, lon), language='en', timeout=10)
        addr = loc.raw.get('address', {})
        return addr.get('country', 'Unknown'), addr.get('city') or addr.get('town') or 'Unknown'
    except: return "Unknown", "Unknown"

# ── 3. Main Application ───────────────────────────────────────────────────────
class MediaSorterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Media Sorter Pro v15.3")
        self.geometry("900x950")
        self.configure(bg="#c8cde0")
        self.progress_val, self.import_folder, self.save_folder = tk.DoubleVar(), tk.StringVar(), tk.StringVar()
        self.custom_prefix, self.min_size_mb = tk.StringVar(value=""), tk.StringVar(value="0")
        self.status_text = tk.StringVar(value="Ready to process.")
        self._build_ui()

    def _build_ui(self):
        BG, PANEL, ACCENT, GREEN = "#c8cde0", "#d8dcea", "#4f46e5", "#15803d"
        tk.Label(self, text="◈ MEDIA SORTER PRO", bg=BG, fg=ACCENT, font=("Segoe UI", 16, "bold")).pack(pady=15)

        path_f = tk.LabelFrame(self, text=" Paths ", bg=PANEL); path_f.pack(fill="x", padx=20, pady=5)
        self._path_row(path_f, "SOURCE:", self.import_folder, self._browse_import, PANEL, BG, ACCENT)
        self._path_row(path_f, "DESTINATION:", self.save_folder, self._browse_save, PANEL, BG, ACCENT)

        opts_f = tk.LabelFrame(self, text=" Task Options ", bg=PANEL); opts_f.pack(fill="x", padx=20, pady=5)
        self.opt_sort_geo, self.opt_rename = tk.BooleanVar(value=STATUS["geopy"]), tk.BooleanVar(value=True)
        self.opt_transfer_mode = tk.StringVar(value="Copy")
        
        tk.Checkbutton(opts_f, text="Geo-Sort", variable=self.opt_sort_geo, bg=PANEL).grid(row=0, column=0, padx=10)
        tk.Checkbutton(opts_f, text="Rename Files", variable=self.opt_rename, bg=PANEL).grid(row=0, column=1, padx=10)
        tk.Radiobutton(opts_f, text="Copy", variable=self.opt_transfer_mode, value="Copy", bg=PANEL).grid(row=0, column=2)
        tk.Radiobutton(opts_f, text="Move", variable=self.opt_transfer_mode, value="Move", bg=PANEL, fg="red").grid(row=0, column=3)

        btn_f = tk.Frame(self, bg=BG); btn_f.pack(fill="x", padx=20, pady=10)
        tk.Button(btn_f, text="▶ START TASK", command=self.start_sorting, bg=GREEN, fg="white", font=("Segoe UI", 10, "bold"), width=30, pady=10).pack(side="left", expand=True)
        tk.Button(btn_f, text="↺ UNDO", command=self.undo_last, bg="#b45309", fg="white", font=("Segoe UI", 9), width=10, pady=10).pack(side="left", padx=5)

        ttk.Progressbar(self, variable=self.progress_val, maximum=100).pack(fill="x", padx=20, pady=5)
        self.log_area = scrolledtext.ScrolledText(self, height=15, state='disabled', font=("Consolas", 9)); self.log_area.pack(fill="both", expand=True, padx=20, pady=5)
        tk.Label(self, textvariable=self.status_text, bd=1, relief="sunken", anchor="w").pack(side="bottom", fill="x")

    def _path_row(self, p, t, v, cmd, pa, b, a):
        r = tk.Frame(p, bg=pa); r.pack(fill="x", padx=10, pady=5)
        tk.Label(r, text=t, bg=pa, width=12, anchor="w").pack(side="left")
        tk.Entry(r, textvariable=v, bg=b).pack(side="left", fill="x", expand=True, padx=5)
        tk.Button(r, text="Browse", command=cmd, bg=a, fg="white", font=("Segoe UI", 8)).pack(side="left")

    def _browse_import(self): 
        p = filedialog.askdirectory(); self.import_folder.set(p); self.log(f"Source: {p}") if p else None
    def _browse_save(self): 
        p = filedialog.askdirectory(); self.save_folder.set(p); self.log(f"Destination: {p}") if p else None

    def log(self, m, l="INFO"):
        def app(): self.log_area.configure(state='normal'); self.log_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {l}: {m}\n"); self.log_area.configure(state='disabled'); self.log_area.see(tk.END)
        self.after(0, app)

    def start_sorting(self):
        if not self.import_folder.get() or not self.save_folder.get(): return messagebox.showwarning("Error", "Missing folders.")
        if self.opt_transfer_mode.get() == "Move" and not messagebox.askyesno("MOVE WARNING", "Move mode deletes source files. Proceed?"): return
        threading.Thread(target=self.run_sorting, args=(Path(self.import_folder.get()), Path(self.save_folder.get())), daemon=True).start()

    def run_sorting(self, src, dst):
        try:
            self.status_text.set("Scanning for files...")
            all_files = []
            for f in src.rglob('*'):
                try:
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS: all_files.append(f)
                except: continue
            
            total = len(all_files); history, hashes, mode = [], set(), self.opt_transfer_mode.get()
            for i, fpath in enumerate(all_files):
                self.after(0, lambda v=(i/total)*100, n=fpath.name: [self.progress_val.set(v), self.status_text.set(f"Processing: {n}")])
                try:
                    h = file_md5(fpath)
                    if h in hashes: sub = "_Duplicates"
                    else:
                        hashes.add(h); dt = datetime.fromtimestamp(fpath.stat().st_mtime); sub = dt.strftime("%Y/%Y-%m"); tag = ""
                        if self.opt_sort_geo.get():
                            gps = get_gps_location(fpath)
                            if gps: _, city = reverse_geocode_details(*gps); sub, tag = f"{sub}/{city}", f"-{city}"; time.sleep(1)
                        name = sanitize_name(f"{dt.strftime('%Y-%m-%d')}{tag}-{fpath.name}") if self.opt_rename.get() else fpath.name
                    t_file = dst / sub / name; t_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(fpath), str(t_file)) if mode == "Move" else shutil.copy2(str(fpath), str(t_file))
                    history.append({"src": str(fpath), "dst": str(t_file), "mode": mode})
                except Exception as e: self.log(f"Error {fpath.name}: {e}")

            if history: HISTORY_FILE.write_text(json.dumps(history))
            if mode == "Move": self.cleanup(src)
            self.status_text.set("Complete"); messagebox.showinfo("Done", f"Handled {len(all_files)} files.")
        except: self.log(traceback.format_exc(), "ERROR")

    def cleanup(self, path):
        for item in path.iterdir():
            if item.is_dir(): self.cleanup(item)
        if path != Path(self.import_folder.get()) and path.is_dir() and not any(path.iterdir()):
            try: path.rmdir()
            except: pass

    def undo_last(self):
        if not HISTORY_FILE.exists(): return
        h = json.loads(HISTORY_FILE.read_text())
        for item in h:
            s, d = Path(item["src"]), Path(item["dst"])
            if item["mode"] == "Move" and d.exists(): s.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(d), str(s))
            elif d.exists(): d.unlink()
        HISTORY_FILE.unlink(); self.log("Undo Finished")

# ── 4. Fixed Login ───────────────────────────────────────────────────────────
class LoginWindow(tk.Toplevel):
    def __init__(self, on_success):
        super().__init__(); self.on_success = on_success; self.title("Access")
        w, h = 300, 150; x = (self.winfo_screenwidth() // 2) - (w // 2); y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f'{w}x{h}+{x}+{y}'); tk.Label(self, text="PASSWORD:", font=("Segoe UI", 9, "bold")).pack(pady=15)
        self.e = tk.Entry(self, show="*", justify="center"); self.e.pack(padx=20, fill="x")
        self.e.bind("<Return>", lambda e: self.validate()); self.e.focus_set()
        tk.Button(self, text="UNLOCK", command=self.validate, bg="#4f46e5", fg="white").pack(pady=15)

    def validate(self):
        # Default: admin
        if hashlib.sha256(self.e.get().encode()).hexdigest() == PASSWORD_HASH: self.destroy(); self.on_success()
        else: messagebox.showerror("Denied", "Invalid")

if __name__ == "__main__":
    root = tk.Tk(); root.withdraw()
    def launch(): app = MediaSorterApp(); app.mainloop(); root.destroy()
    LoginWindow(launch); root.mainloop()
