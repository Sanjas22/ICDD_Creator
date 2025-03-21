import os
import uuid
import shutil
from tkinter import filedialog, simpledialog, messagebox
from rdflib import Graph, URIRef, Literal, Namespace, RDF, XSD
import logging
from Core.file_utils import make_icdd_archive

logger = logging.getLogger(__name__)

# Set the path to the local ontologies if it differs from this one.
LOCAL_ONTOLOGIES_PATH = os.path.join(os.path.dirname(__file__), '..', 'local_ontologies')

def create_icdd():
    logger.info("Starting ICDD creation...")
    base_uri = simpledialog.askstring("Input", "Enter the Base URI:", initialvalue="http://example.com/container")
    if not base_uri:
        messagebox.showwarning("ICDD Creation", "The Base URI has not been entered.")
        return

    publisher_name = simpledialog.askstring("Input", "Enter the publisher's name:")
    if not publisher_name:
        messagebox.showwarning("ICDD Creation", "The publisher's name is not specified.")
        return

    directory = filedialog.askdirectory(title="Select the folder to create the ICDD.")
    if not directory:
        messagebox.showwarning("ICDD Creation", "Folder not selected.")
        return

    container_name = simpledialog.askstring("Input", "Enter the name of the ICDD container:")
    if not container_name:
        messagebox.showwarning("ICDD Creation", "The container name is not specified.")
        return

    icdd_dir = os.path.join(directory, container_name)
    os.makedirs(icdd_dir, exist_ok=True)
    for sub in ['Ontology resources', 'Payload documents', 'Payload triples']:
        os.makedirs(os.path.join(icdd_dir, sub), exist_ok=True)

    # Copying Ontologies
    ontologies = ['Container.rdf', 'Linkset.rdf', 'ExtendedLinkset.rdf']
    for filename in ontologies:
        src = os.path.join(LOCAL_ONTOLOGIES_PATH, filename)
        dst = os.path.join(icdd_dir, 'Ontology resources', filename)
        if os.path.exists(src):
            shutil.copy(src, dst)
            logger.debug(f"Copied the ontology: {filename}")
        else:
            messagebox.showerror("Ontology Error", f"{filename} not found.")

    # Generating an Index.rdf
    g = Graph()
    CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
    OWL = Namespace("http://www.w3.org/2002/07/owl#")
    g.bind("ct", CT)
    g.bind("owl", OWL)

    container_uri = URIRef(f"{base_uri}/ContainerDescription{uuid.uuid4()}")
    publisher_uri = URIRef(f"{base_uri}/Party{uuid.uuid4()}")
    g.add((container_uri, RDF.type, CT.ContainerDescription))
    g.add((container_uri, CT.conformanceIndicator, Literal("ICDD-Part1-Container", datatype=XSD.string)))
    g.add((container_uri, CT.publishedBy, publisher_uri))
    g.add((publisher_uri, RDF.type, CT.Party))
    g.add((publisher_uri, CT.name, Literal(publisher_name, datatype=XSD.string)))

    ontology = URIRef(base_uri)
    g.add((ontology, RDF.type, OWL.Ontology))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-1/ed-1/en/Container.rdf")))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset.rdf")))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-2/ed-1/en/ExtendedLinkset.rdf")))

    index_path = os.path.join(icdd_dir, 'Index.rdf')
    g.serialize(destination=index_path, format='pretty-xml')
    logger.info(f"Index.rdf created in {index_path}")

    # Archiving the ICDD (.icdd)
    icdd_archive = f"{icdd_dir}.icdd"
    make_icdd_archive(icdd_dir, icdd_archive)
    messagebox.showinfo("ICDD Creation", f"ICDD контейнер создан: {icdd_archive}")
    logger.info(f"ICDD создан: {icdd_archive}")
