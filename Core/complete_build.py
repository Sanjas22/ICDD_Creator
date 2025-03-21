# Core/complete_build.py

import os
import shutil
import uuid
import logging
from tkinter import simpledialog, filedialog, messagebox
from rdflib import Graph, Namespace, RDF, Literal, XSD, URIRef

from Core.file_utils import remove_repeated_segments, flatten_double_cde_backup
from Core.rdf_utils import generate_uri, find_document_uri
from Core.import_cde import import_cde_backup
from Core.import_csv import process_csv_links

logger = logging.getLogger(__name__)

def build_complete_icdd():
    """
    Combined operation to build an ICDD:
      1. Ask for basic data (Base URI, container name, publisher).
      2. Create a basic ICDD container (structure, Index.rdf, copy ontologies).
      3. (Optional) Import CDE Backup into that container (ask_save=False).
      4. (Optional) Import CSV/IFC links into that container (ask_save=False).
      5. Finally, prompt once to save the resulting .icdd.
    """
    # --- Step 1: Collect basic data ---
    base_uri = simpledialog.askstring(
        "Input",
        "Enter Base URI:",
        initialvalue="http://example.com/container"
    )
    if not base_uri:
        messagebox.showwarning("Create ICDD", "Base URI not specified.")
        return

    publisher_name = simpledialog.askstring(
        "Input",
        "Enter the publisher name:"
    )
    if not publisher_name:
        messagebox.showwarning("Create ICDD", "Publisher name not specified.")
        return

    container_name = simpledialog.askstring(
        "Input",
        "Enter the ICDD container name:"
    )
    if not container_name:
        messagebox.showwarning("Create ICDD", "Container name not specified.")
        return

    folder = filedialog.askdirectory(
        title="Select the folder to create the ICDD"
    )
    if not folder:
        messagebox.showwarning("Create ICDD", "No folder selected.")
        return

    # The new container folder
    container_dir = os.path.join(folder, container_name)
    os.makedirs(container_dir, exist_ok=True)

    # Create needed subdirectories
    for sub in ['Ontology resources', 'Payload documents', 'Payload triples']:
        os.makedirs(os.path.join(container_dir, sub), exist_ok=True)

    # --- Step 2: Create the basic container (Index.rdf + ontologies) ---
    local_ontologies_path = os.path.join(
        os.path.dirname(__file__),
        '..',
        'local_ontologies'
    )
    ontologies = ['Container.rdf', 'Linkset.rdf', 'ExtendedLinkset.rdf']

    for filename in ontologies:
        src = os.path.join(local_ontologies_path, filename)
        dst = os.path.join(container_dir, 'Ontology resources', filename)
        if os.path.exists(src):
            shutil.copy(src, dst)
            logger.debug(f"Copied ontology: {filename}")
        else:
            messagebox.showerror("Ontology Error", f"{filename} not found.")
            return

    g = Graph()
    CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
    OWL = Namespace("http://www.w3.org/2002/07/owl#")
    g.bind("ct", CT)
    g.bind("owl", OWL)

    container_uri = URIRef(f"{base_uri}/ContainerDescription{uuid.uuid4()}")
    publisher_uri = URIRef(f"{base_uri}/Party{uuid.uuid4()}")

    # Container type
    g.add((container_uri, RDF.type, CT.ContainerDescription))
    g.add((
        container_uri,
        CT.conformanceIndicator,
        Literal("ICDD-Part1-Container", datatype=XSD.string)
    ))
    # Publisher link
    g.add((container_uri, CT.publishedBy, publisher_uri))
    g.add((publisher_uri, RDF.type, CT.Party))
    g.add((publisher_uri, CT.name, Literal(publisher_name, datatype=XSD.string)))

    # Ontology
    ontology = URIRef(base_uri)
    g.add((ontology, RDF.type, OWL.Ontology))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-1/ed-1/en/Container.rdf")))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset.rdf")))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-2/ed-1/en/ExtendedLinkset.rdf")))

    index_path = os.path.join(container_dir, "Index.rdf")
    g.serialize(destination=index_path, format='pretty-xml')
    logger.info(f"Index.rdf created at {index_path}")

    # --- Step 3: (Optional) Import CDE Backup ---
    if messagebox.askyesno("CDE Backup", "Would you like to import CDE Backup into this container?"):
        # Pass the container_dir and ask_save=False, so no extra "save" is done
        import_cde_backup(container_dir=container_dir, ask_save=False)

    # --- Step 4: (Optional) Import CSV/IFC links ---
    if messagebox.askyesno("CSV/IFC Links", "Would you like to import CSV/IFC links?"):
        process_csv_links(container_dir=container_dir, ask_save=False)

    # --- Step 5: Final save of the container (once) ---
    updated_icdd_path = filedialog.asksaveasfilename(
        title="Save the final ICDD container",
        defaultextension=".icdd",
        filetypes=[("ICDD files", "*.icdd")]
    )
    if not updated_icdd_path:
        messagebox.showwarning("Saving", "No file selected, operation cancelled.")
        return

    # Archive the container
    shutil.make_archive(container_dir, 'zip', container_dir)
    icdd_final = f"{container_dir}.zip"
    os.rename(icdd_final, updated_icdd_path)

    messagebox.showinfo(
        "Success",
        f"The final ICDD container has been saved:\n{updated_icdd_path}"
    )
    logger.info(f"The final ICDD container has been saved: {updated_icdd_path}")


if __name__ == "__main__":
    build_complete_icdd()
