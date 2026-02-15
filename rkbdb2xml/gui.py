import threading
from pathlib import Path
from typing import List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase

from .rkbdb2xml import export_rekordbox_db_to_xml


class RekordboxExporterGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("rkbdb2xml GUI")
        self._playlist_rows: List[dict] = []
        self._settings_file = Path.home() / ".rkbdb2xml_gui_settings.json"
        self._create_widgets()
        self._load_last_settings()

    def _create_widgets(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.grid(row=0, column=0, sticky="nsew")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main.columnconfigure(1, weight=1)

        # DB path
        ttk.Label(main, text="Rekordbox DB path (optional)").grid(row=0, column=0, sticky="w")
        self.db_path_var = tk.StringVar()
        db_entry = ttk.Entry(main, textvariable=self.db_path_var)
        db_entry.grid(row=0, column=1, sticky="ew", padx=(5, 5))
        ttk.Button(main, text="Browse", command=self._browse_db).grid(row=0, column=2, sticky="w")

        # Output XML
        ttk.Label(main, text="Output XML file").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.output_path_var = tk.StringVar()
        out_entry = ttk.Entry(main, textvariable=self.output_path_var)
        out_entry.grid(row=1, column=1, sticky="ew", padx=(5, 5), pady=(5, 0))
        ttk.Button(main, text="Browse", command=self._browse_output).grid(row=1, column=2, sticky="w", pady=(5, 0))

        # DB key
        ttk.Label(main, text="DB key (optional)").grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.db_key_var = tk.StringVar()
        key_entry = ttk.Entry(main, textvariable=self.db_key_var)
        key_entry.grid(row=2, column=1, sticky="ew", padx=(5, 5), pady=(5, 0))

        # Options row
        options_frame = ttk.Frame(main)
        options_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self.verbose_var = tk.BooleanVar(value=True)
        self.force_var = tk.BooleanVar(value=False)
        self.roman_var = tk.BooleanVar(value=True)
        self.bpm_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(options_frame, text="Verbose", variable=self.verbose_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options_frame, text="Force overwrite", variable=self.force_var).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Checkbutton(options_frame, text="Roman (romaji)", variable=self.roman_var).grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Checkbutton(options_frame, text="BPM in title", variable=self.bpm_var).grid(row=0, column=3, sticky="w", padx=(10, 0))

        # Order by
        ttk.Label(main, text="Order by").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.orderby_var = tk.StringVar(value="bpm")
        order_combo = ttk.Combobox(main, textvariable=self.orderby_var, state="readonly", values=["default", "bpm"])
        order_combo.grid(row=4, column=1, sticky="w", padx=(5, 5), pady=(10, 0))

        # Playlists section
        ttk.Label(main, text="Playlists").grid(row=5, column=0, sticky="nw", pady=(10, 0))
        playlists_frame = ttk.Frame(main)
        playlists_frame.grid(row=5, column=1, columnspan=2, sticky="nsew", padx=(5, 5), pady=(10, 0))

        playlists_frame.columnconfigure(0, weight=1)
        playlists_frame.rowconfigure(1, weight=1)

        load_btn = ttk.Button(playlists_frame, text="Load playlists from DB", command=self._load_playlists)
        load_btn.grid(row=0, column=0, sticky="w")

        self.playlists_listbox = tk.Listbox(
            playlists_frame,
            selectmode="extended",
            exportselection=False,
        )
        self.playlists_listbox.grid(row=1, column=0, sticky="nsew")
        pl_scrollbar = ttk.Scrollbar(playlists_frame, orient="vertical", command=self.playlists_listbox.yview)
        pl_scrollbar.grid(row=1, column=1, sticky="ns")
        self.playlists_listbox.configure(yscrollcommand=pl_scrollbar.set)

        # Run button
        self.run_button = ttk.Button(main, text="Export", command=self._on_run)
        self.run_button.grid(row=6, column=0, columnspan=3, pady=(10, 0))

        # Log output
        ttk.Label(main, text="Log").grid(row=7, column=0, sticky="nw", pady=(10, 0))
        log_frame = ttk.Frame(main)
        log_frame.grid(row=7, column=1, columnspan=2, sticky="nsew", pady=(10, 0))

        main.rowconfigure(7, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _load_last_settings(self) -> None:
        """Load last used settings from a JSON file."""
        if not self._settings_file.exists():
            return
        try:
            import json

            with self._settings_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self.db_path_var.set(data.get("db_path", ""))
            self.output_path_var.set(data.get("output_path", ""))
            self.db_key_var.set(data.get("db_key", ""))
            self.verbose_var.set(data.get("verbose", True))
            self.force_var.set(data.get("force", False))
            self.roman_var.set(data.get("roman", True))
            self.bpm_var.set(data.get("bpm", True))
            self.orderby_var.set(data.get("orderby", "bpm"))
            # playlists selection is not auto-restored because it depends on loaded DB state
        except Exception:
            # fail silently; we don't want to block startup
            return

    def _save_last_settings(self) -> None:
        """Persist current settings to a JSON file."""
        try:
            import json

            data = {
                "db_path": self.db_path_var.get(),
                "output_path": self.output_path_var.get(),
                "db_key": self.db_key_var.get(),
                "verbose": self.verbose_var.get(),
                "force": self.force_var.get(),
                "roman": self.roman_var.get(),
                "bpm": self.bpm_var.get(),
                "orderby": self.orderby_var.get(),
            }
            with self._settings_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            # Do not raise to UI; best-effort
            pass

    def _browse_db(self) -> None:
        filename = filedialog.askopenfilename(title="Select Rekordbox DB file")
        if filename:
            self.db_path_var.set(filename)

    def _browse_output(self) -> None:
        filename = filedialog.asksaveasfilename(title="Select output XML file", defaultextension=".xml", filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
        if filename:
            self.output_path_var.set(filename)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _load_playlists(self) -> None:
        """Load playlists from Rekordbox database and populate the listbox.

        Uses the same database auto-detection behavior as the CLI when no
        explicit path is provided. Only non-folder playlists are selectable.
        """
        db_path = self.db_path_var.get().strip() or None
        db_path_str: Optional[str] = db_path if db_path else None

        try:
            db = RekordboxDatabase(db_path_str)
            pls = db.get_playlist().all()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to load playlists: {e}")
            return

        id_map = {pl.ID: pl for pl in pls}
        parent_map: dict = {}
        for pl in pls:
            parent_map.setdefault(pl.ParentID, []).append(pl)

        for children in parent_map.values():
            children.sort(key=lambda x: x.Name)

        rows: List[dict] = []

        def traverse(pid: Optional[int], depth: int, parent_path: str) -> None:
            for pl in parent_map.get(pid, []):
                name_indented = "  " * depth + pl.Name
                path_str = f"{parent_path}/{pl.Name}" if parent_path else pl.Name
                rows.append(
                    {
                        "id": pl.ID,
                        "name": name_indented,
                        "is_folder": pl.is_folder,
                        "parent_id": pl.ParentID,
                        "path": path_str,
                    }
                )
                traverse(pl.ID, depth + 1, path_str)

        root_parents = [pid for pid in parent_map.keys() if pid not in id_map]
        for rp in root_parents:
            traverse(rp, 0, "")

        self.playlists_listbox.delete(0, "end")
        self._playlist_rows = []
        for r in rows:
            if r["is_folder"]:
                continue
            self.playlists_listbox.insert("end", r["name"])
            self._playlist_rows.append(r)

        if not self._playlist_rows:
            self._append_log("No playlists found in database.")
        else:
            self._append_log(f"Loaded {len(self._playlist_rows)} playlists.")

    def _on_run(self) -> None:
        db_path = self.db_path_var.get().strip() or None
        output_path = self.output_path_var.get().strip()
        db_key = self.db_key_var.get().strip() or None

        if not output_path:
            messagebox.showerror("Error", "Output XML file is required.")
            return

        # Normalize output path:
        # - expand user (~)
        # - if relative, make it absolute (cwd basis)
        # - if no suffix, append .xml
        output = Path(output_path).expanduser()
        if not output.is_absolute():
            output = Path.cwd() / output
        if output.suffix.lower() != ".xml":
            output = output.with_suffix(".xml")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to create output directory: {e}")
            return

        if output.exists():
            if self.force_var.get():
                if output.is_file():
                    try:
                        output.unlink()
                    except Exception as e:  # noqa: BLE001
                        messagebox.showerror("Error", f"Failed to remove existing file: {e}")
                        return
                else:
                    messagebox.showerror("Error", f"Output path exists and is not a file: {output}")
                    return
            else:
                if not messagebox.askyesno("Overwrite?", f"Output file {output} already exists. Overwrite?"):
                    return
                if output.is_file():
                    try:
                        output.unlink()
                    except Exception as e:  # noqa: BLE001
                        messagebox.showerror("Error", f"Failed to remove existing file: {e}")
                        return
                else:
                    messagebox.showerror("Error", f"Output path exists and is not a file: {output}")
                    return

        playlists: Optional[List[str]] = None
        if self._playlist_rows and self.playlists_listbox.curselection():
            # Use hierarchical path strings so exporter can match by path reliably
            playlists = [
                self._playlist_rows[idx]["path"]
                for idx in self.playlists_listbox.curselection()
            ]

        verbose = self.verbose_var.get()
        roman = self.roman_var.get()
        bpm = self.bpm_var.get()
        orderby = self.orderby_var.get() or "default"

        self.run_button.config(state="disabled")
        self._append_log("Starting export...")

        def worker() -> None:
            try:
                export_rekordbox_db_to_xml(
                    db_path,
                    str(output),
                    db_key,
                    verbose,
                    roman,
                    bpm,
                    orderby,
                    playlists,
                )
                self.after(0, lambda: self._append_log("Export completed successfully."))
            except Exception as e:  # noqa: BLE001
                def on_error(err=e) -> None:
                    self._append_log(f"Error: {err}")
                    messagebox.showerror("Error", f"Failed to export: {err}")

                self.after(0, on_error)
            finally:
                self.after(0, lambda: self.run_button.config(state="normal"))
                self.after(0, self._save_last_settings)

        threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    app = RekordboxExporterGUI()
    app.geometry("800x600")
    app.mainloop()


if __name__ == "__main__":
    main()
