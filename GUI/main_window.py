import tkinter as tk
from tkinter import messagebox
import logging

from Core.create_icdd import create_icdd
from Core.open_icdd import open_icdd
from Core.import_cde import import_cde_backup
from Core.import_csv import process_csv_links
from Core.complete_build import build_complete_icdd

logger = logging.getLogger(__name__)

def run_gui():
    root = tk.Tk()
    root.title("ICDD Tool")
    root.geometry("300x700")

    btn_create = tk.Button(root, text="Create ICDD", command=create_icdd, width=25)
    btn_open = tk.Button(root, text="Open ICDD", command=open_icdd, width=25)
    btn_import_cde = tk.Button(root, text="Import CDE Backup", command=import_cde_backup, width=25)
    btn_import_csv = tk.Button(root, text="Import CSV/IFC Links", command=process_csv_links, width=25)
    btn_complete = tk.Button(root, text="Build Complete ICDD", command=build_complete_icdd, width=25)

    btn_create.pack(pady=10)
    btn_open.pack(pady=10)
    btn_import_cde.pack(pady=10)
    btn_import_csv.pack(pady=10)
    btn_complete.pack(pady=10)

    root.mainloop()

if __name__ == '__main__':
    try:
        run_gui()
    except Exception as e:
        messagebox.showerror("Fatal Error", str(e))
        logging.exception("Uncaught error in GUI")
