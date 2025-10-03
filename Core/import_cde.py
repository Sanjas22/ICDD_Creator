# Core/import_cde.py

import os
import zipfile
import tempfile
import shutil
import logging
from tkinter import filedialog, messagebox
from rdflib import Graph, Namespace, RDF
from Core.file_utils import remove_repeated_segments, flatten_double_cde_backup
from Core.rdf_utils import add_documents_flat

logger = logging.getLogger(__name__)


def import_cde_backup(container_dir=None, ask_save=True):

    logger.info("Import CDE Backup started.")

    # 1) If container_dir == None, we work in single mode:
    icdd_temp_dir = None
    if container_dir is None:
        # ask which ICDD file to update
        icdd_file_path = filedialog.askopenfilename(
            title="Select ICDD file for import",
            filetypes=[("ICDD files", "*.icdd"), ("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if not icdd_file_path:
            messagebox.showwarning("Selection Error", "No ICDD file selected.")
            return

        # Unpack the selected ICDD into a temporary directory
        icdd_temp_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(icdd_file_path, 'r') as zip_ref:
                zip_ref.extractall(icdd_temp_dir)
            logger.info(f"ICDD extracted into {icdd_temp_dir}")

            # Now we work with this temp ICDD
            container_dir = icdd_temp_dir

        except Exception as e:
            logger.error(f"Error extracting ICDD: {e}")
            messagebox.showerror("ICDD Extraction Error", f"Error: {e}")
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
            return

    # 2) Select CDE Backup ZIP (in any mode)
    cde_backup_path = filedialog.askopenfilename(
        title="Select CDE Backup file",
        filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
    )
    if not cde_backup_path:
        messagebox.showwarning("Selection Error", "No CDE Backup file selected.")
        # If we are in single mode, need to remove the temp dir
        if icdd_temp_dir:
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        return

    # 3) Extract CDE Backup to a temporary directory
    cde_temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cde_backup_path, 'r') as zip_ref:
            zip_ref.extractall(cde_temp_dir)
        logger.info(f"CDE Backup extracted into {cde_temp_dir}")

        # Flatten nested CDE
        flatten_double_cde_backup(cde_temp_dir)

        # The user selects folders and files from CDE.
        messagebox.showinfo(
            "Select Folders",
            "Select folders to copy from CDE Backup.\nClick 'Cancel' when finished."
        )
        selected_folders = []
        while True:
            folder_path = filedialog.askdirectory(
                title="Select folder from CDE Backup",
                initialdir=cde_temp_dir
            )
            if not folder_path:
                break
            selected_folders.append(os.path.abspath(folder_path))

        selected_files = filedialog.askopenfilenames(
            title="Select files from CDE Backup",
            initialdir=cde_temp_dir,
            filetypes=[("All files", "*.*")]
        )

        # 4) Copy the selected items to Payload documents
        payload_documents_path = os.path.join(container_dir, 'Payload documents')
        os.makedirs(payload_documents_path, exist_ok=True)

        for folder in selected_folders:
            rel = os.path.relpath(folder, cde_temp_dir)
            rel = remove_repeated_segments(rel).replace("\\", "/")
            dest = os.path.join(payload_documents_path, rel)
            shutil.copytree(folder, dest, dirs_exist_ok=True)

        for file in selected_files:
            rel = os.path.relpath(file, cde_temp_dir)
            rel = remove_repeated_segments(rel).replace("\\", "/")
            dest = os.path.join(payload_documents_path, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(file, dest)

        # 5) Update Index.rdf (located in container_dir)
        index_path = os.path.join(container_dir, 'Index.rdf')
        if not os.path.exists(index_path):
            messagebox.showerror("Index Error", "Index.rdf not found in the container.")
            return

        g = Graph()
        g.parse(index_path)
        CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
        container_uri = None
        for s, p, o in g.triples((None, RDF.type, CT.ContainerDescription)):
            container_uri = s
            break
        if not container_uri:
            messagebox.showerror("Index Error", "No ContainerDescription found in Index.rdf")
            return

        add_documents_flat(g, CT, container_uri, container_uri.rsplit("/", 1)[0], payload_documents_path)
        g.serialize(destination=index_path, format='pretty-xml')
        logger.info("Index.rdf updated after CDE Backup import (no linkset).")

        # 6) If ask_save=True, pack it back (only for single mode
        #    or if the user really wants to save)
        if ask_save:
            updated_icdd_path = filedialog.asksaveasfilename(
                title="Save updated ICDD",
                defaultextension=".icdd",
                filetypes=[("ICDD files", "*.icdd")]
            )
            if updated_icdd_path:
                # Archive container_dir
                shutil.make_archive(container_dir, 'zip', container_dir)
                os.rename(f"{container_dir}.zip", updated_icdd_path)
                messagebox.showinfo("Import Success", f"Updated ICDD saved: {updated_icdd_path}")
                logger.info(f"Updated ICDD saved: {updated_icdd_path}")
            else:
                messagebox.showwarning("Save Error", "No save location selected.")

    except Exception as e:
        logger.error(f"Error importing CDE Backup: {e}")
        messagebox.showerror("CDE Import Error", f"Error: {e}")
    finally:
        # If we are in single mode (icdd_temp_dir != None),
        # and ask_save=True, then we have already saved => delete temp
        # If ask_save=False, then this temp is not needed anyway
        if icdd_temp_dir:
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        shutil.rmtree(cde_temp_dir, ignore_errors=True)
