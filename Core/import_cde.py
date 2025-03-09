import os
import zipfile
import tempfile
import shutil
import logging
from tkinter import filedialog, messagebox
from rdflib import Graph, Namespace, RDF, Literal, XSD

from Core.file_utils import flatten_double_cde_backup, remove_repeated_segments
from Core.rdf_utils import add_documents_flat

logger = logging.getLogger(__name__)

def import_cde_backup():
    logger.info("CDE Backup import is running.")
    icdd_file_path = filedialog.askopenfilename(
        title="Select the ICDD file to import",
        filetypes=[("ICDD files", "*.icdd"), ("ZIP files", "*.zip"), ("All files", "*.*")]
    )
    if not icdd_file_path:
        messagebox.showwarning("Selection Error", "The ICDD file is not selected.")
        return

    icdd_temp_dir = tempfile.mkdtemp()
    cde_temp_dir = None
    try:
        # Extracting the ICDD container
        with zipfile.ZipFile(icdd_file_path, 'r') as zip_ref:
            zip_ref.extractall(icdd_temp_dir)
        logger.info(f"ICDD extracted в {icdd_temp_dir}")

        payload_documents_path = os.path.join(icdd_temp_dir, 'Payload documents')
        os.makedirs(payload_documents_path, exist_ok=True)

        # Selecting the CDE Backup file
        cde_backup_path = filedialog.askopenfilename(
            title="Select the СDE Backup file",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if not cde_backup_path:
            messagebox.showwarning("Selection Error", "The CDE Backup file is not selected.")
            shutil.rmtree(icdd_temp_dir)
            return

        cde_temp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(cde_backup_path, 'r') as zip_ref:
            zip_ref.extractall(cde_temp_dir)
        logger.info(f"CDE Backup extracted в {cde_temp_dir}")

        flatten_double_cde_backup(cde_temp_dir)

        # The user selects folders from CDE Backup to copy
        messagebox.showinfo("Select Folders",
            "Select the folders to copy from CDE Backup.\nClick 'Cancel' when you're done.")
        selected_folders = []
        while True:
            folder_path = filedialog.askdirectory(title="Select a folder from CDE Backup", initialdir=cde_temp_dir)
            if not folder_path:
                break
            selected_folders.append(os.path.abspath(folder_path))

        # Selecting files from CD Backup
        selected_files = filedialog.askopenfilenames(title="Select files from CD Backup", initialdir=cde_temp_dir)

        # Copying selected folders
        for folder in selected_folders:
            rel = remove_repeated_segments(os.path.relpath(folder, cde_temp_dir)).replace("\\", "/")
            dest = os.path.join(payload_documents_path, rel)
            shutil.copytree(folder, dest, dirs_exist_ok=True)

        # Copying selected files
        for file in selected_files:
            rel = remove_repeated_segments(os.path.relpath(file, cde_temp_dir)).replace("\\", "/")
            dest = os.path.join(payload_documents_path, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(file, dest)

        # Updating Index.rdf: adding new documents (without creating a Linkset)
        index_path = os.path.join(icdd_temp_dir, 'Index.rdf')
        g = Graph()
        g.parse(index_path)
        CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
        container_uri = None
        for s, p, o in g.triples((None, RDF.type, CT.ContainerDescription)):
            container_uri = s
            break
        if container_uri is None:
            messagebox.showerror("Index Error", "ContainerDescription not found в Index.rdf")
            shutil.rmtree(icdd_temp_dir)
            shutil.rmtree(cde_temp_dir)
            return

        base_uri = str(container_uri).rsplit("/", 1)[0]
        # Adding documents in a flat structure
        add_documents_flat(g, CT, container_uri, base_uri, payload_documents_path)
        g.serialize(destination=index_path, format='pretty-xml')
        logger.info("Index.rdf updated.")

        # Requesting a location to save the updated ICDD
        updated_icdd_path = filedialog.asksaveasfilename(
            title="Save the updated ICDD",
            defaultextension=".icdd",
            filetypes=[("ICDD files", "*.icdd")]
        )
        if not updated_icdd_path:
            messagebox.showwarning("Save Error", "The save location has not been selected.")
            shutil.rmtree(icdd_temp_dir)
            shutil.rmtree(cde_temp_dir)
            return

        shutil.make_archive(icdd_temp_dir, 'zip', icdd_temp_dir)
        os.rename(f"{icdd_temp_dir}.zip", updated_icdd_path)
        messagebox.showinfo("Import Success", f"Updated ICDD is saved: {updated_icdd_path}")
        logger.info(f"Updated ICDD is saved: {updated_icdd_path}")

    except Exception as e:
        logger.error(f"Error when importing CD Backup: {e}")
        messagebox.showerror("CDE Import Error", f"Error: {e}")
    finally:
        if os.path.exists(icdd_temp_dir):
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        if cde_temp_dir and os.path.exists(cde_temp_dir):
            shutil.rmtree(cde_temp_dir, ignore_errors=True)

if __name__ == "__main__":
    import_cde_backup()
