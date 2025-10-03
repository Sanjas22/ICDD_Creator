# Core/import_csv.py

import os
import zipfile
import tempfile
import shutil
import csv
import uuid
import logging
from tkinter import filedialog, messagebox
from rdflib import Graph, Namespace, RDF, Literal, XSD, URIRef

# If IfcOpenShell is installed, import for IFC processing
try:
    import ifcopenshell
except ImportError:
    ifcopenshell = None

from Core.rdf_utils import (
    find_document_uri,
    generate_uri,
    create_directed_link,
    build_iso_semantics_index,
    normalize_csv_type_to_iso,
)
from Core.file_utils import remove_repeated_segments

logger = logging.getLogger(__name__)

def process_csv_links(container_dir=None, ask_save=True):
    """
    Imports CSV/IFC links into an ICDD container (ISO-only):
      - Each row becomes an ls:Link with two ls:LinkElement (from/to) and ls:hasDocument on each.
      - The semantic type is taken from ExtendedLinkset.rdf (els:*) using aliases for common human terms.
      - Structure is chosen automatically (ls:Directed1toNLink or ls:DirectedBinaryLink).
      - If a CSV type is not recognized, we still create a valid ISO link (1→N) and add rdfs:comment note.
      - If GUID is provided, we attach ls:StringBasedIdentifier to the TO end.
      - For IFC (optional), we can add HasPart links inside the IFC document, anchoring by GUID/Project.
    """

    logger.info("Importing CSV/IFC links...")

    # Standalone mode: ask user for ICDD file
    icdd_temp_dir = None
    if container_dir is None:
        icdd_file_path = filedialog.askopenfilename(
            title="Select ICDD file to update links",
            filetypes=[("ICDD files", "*.icdd"), ("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if not icdd_file_path:
            messagebox.showwarning("Error", "No ICDD file selected.")
            return

        # Extract chosen ICDD into temp
        icdd_temp_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(icdd_file_path, 'r') as zip_ref:
                zip_ref.extractall(icdd_temp_dir)
            logger.info(f"ICDD extracted into {icdd_temp_dir}")

            # Now we treat that temp folder as container_dir
            container_dir = icdd_temp_dir

        except Exception as e:
            messagebox.showerror("Error", f"ICDD extraction error: {e}")
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
            return

    # 1) Ask for CSV file
    csv_file_path = filedialog.askopenfilename(
        title="Select the CSV file with links",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    if not csv_file_path:
        messagebox.showwarning("Error", "CSV file not selected.")
        if icdd_temp_dir:
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        return

    # 2) Load Index.rdf from container_dir
    index_path = os.path.join(container_dir, 'Index.rdf')
    if not os.path.exists(index_path):
        messagebox.showerror("Error", "Index.rdf not found in the container.")
        if icdd_temp_dir:
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        return

    g_index = Graph()
    try:
        g_index.parse(index_path)
    except Exception as e:
        messagebox.showerror("Error", f"Parsing error for Index.rdf: {e}")
        if icdd_temp_dir:
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        return

    CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
    container_uri = None
    for s, p, o in g_index.triples((None, RDF.type, CT.ContainerDescription)):
        container_uri = s
        break
    if container_uri is None:
        messagebox.showerror("Error", "ContainerDescription not found in Index.rdf")
        if icdd_temp_dir:
            shutil.rmtree(icdd_temp_dir, ignore_errors=True)
        return

    base_uri = str(container_uri).rsplit("/", 1)[0]
    logger.debug(f"Base URI: {base_uri}")

    # 3) Find IFC files in Index.rdf
    ifc_uris = []
    for s, p, o in g_index.triples((None, CT.filetype, None)):
        if ".ifc" in str(o).strip().lower():
            ifc_uris.append(s)
    if ifc_uris:
        logger.info(f"IFC documents found: {len(ifc_uris)}")
    else:
        logger.info("No IFC files found in Index.rdf.")

    # 4) Build a dict of IFC objects (IfcWall, IfcProduct) if ifcopenshell is installed
    ifc_objects_dict = {}
    if ifc_uris and ifcopenshell:
        for ifc_uri in ifc_uris:
            # find the IFC filename
            ifc_filename = None
            for s, p, o in g_index.triples((ifc_uri, CT.filename, None)):
                ifc_filename = str(o).strip()
                break
            if ifc_filename:
                full_ifc_path = os.path.join(container_dir, "Payload documents", os.path.normpath(ifc_filename))
                logger.info(f"IFC full path: {full_ifc_path}")
                if not os.path.exists(full_ifc_path):
                    logger.error(f"IFC file not found at {full_ifc_path}")
                else:
                    try:
                        ifc_file = ifcopenshell.open(full_ifc_path)
                        objs = ifc_file.by_type("IfcWall")
                        if not objs:
                            logger.info("No IfcWall found, trying IfcProduct.")
                            objs = ifc_file.by_type("IfcProduct")
                        for obj in objs:
                            if hasattr(obj, "GlobalId"):
                                ifc_objects_dict[obj.GlobalId] = obj
                    except Exception as e:
                        logger.error(f"Error processing IFC {ifc_filename}: {e}")
    else:
        if not ifcopenshell:
            logger.warning("IfcOpenShell not installed. IFC objects won't be processed automatically.")

    # 5) Create a new RDF graph for links
    g_links = Graph()
    LS  = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset#")
    ELS = Namespace("https://standards.iso.org/iso/21597/-2/ed-1/en/ExtendedLinkset#")
    g_links.bind("ls", LS)
    g_links.bind("els", ELS)
    g_links.bind("owl", "http://www.w3.org/2002/07/owl#")
    g_links.bind("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    g_links.bind("ct", CT)

    # 5.1) Build ISO semantics index (from Ontology resources/ExtendedLinkset.rdf)
    els_path = os.path.join(container_dir, "Ontology resources", "ExtendedLinkset.rdf")
    name_to_uri, g_els = build_iso_semantics_index(els_path)
    if not name_to_uri:
        logger.warning("ExtendedLinkset index is empty. Semantic mapping will be limited to aliases; "
                       "unrecognized types will fall back to generic ls:Link + ls:Directed1toNLink.")

    # 6) Read CSV lines
    try:
        with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
            sample = csvfile.read(1024)
            csvfile.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(csvfile, delimiter=dialect.delimiter)

            required_columns = {"fromPath", "toPath", "Type"}
            if not required_columns.issubset(reader.fieldnames):
                messagebox.showerror("CSV Error", f"CSV must contain columns: {', '.join(required_columns)}")
                return

            for row in reader:
                from_path = row["fromPath"].strip().lstrip("\\/").replace("\\", "/")
                to_path   = row["toPath"].strip().lstrip("\\/").replace("\\", "/")
                relation_type = (row["Type"] or "").strip()

                from_uri = find_document_uri(g_index, CT, from_path)
                to_uri   = find_document_uri(g_index, CT, to_path)
                if not from_uri or not to_uri:
                    logger.warning(f"Documents not found for: {from_path} or {to_path}")
                    continue

                # Prepare optional identifier (GUID on TO end)
                guid_value = (row.get("GUID") or "").strip()
                to_identifier = {"kind": "string", "value": guid_value, "field": "GUID"} if guid_value else None

                # Map CSV type to ISO sem.type + structural kind
                sem_uri, structural_kind = normalize_csv_type_to_iso(relation_type, name_to_uri, g_els)
                note = None
                if sem_uri is None:
                    note = f"Unmapped CSV Type: '{relation_type}'"
                    logger.warning(note)

                # Create ISO link
                create_directed_link(
                    g=g_links,
                    LS_ns=LS,
                    base_uri=base_uri,
                    from_document_uri=from_uri,   # ct:Document from Index.rdf
                    to_document_uri=to_uri,       # ct:Document from Index.rdf
                    sem_uri=sem_uri,              # ELS:* or None
                    structural_kind=structural_kind,  # "Directed1toN"/"DirectedBinary"
                    to_identifier=to_identifier,  # identifier on TO end (if GUID present)
                    note=note
                )

                # If GUID exists and IFC is present → add HasPart inside IFC (anchor by GUID)
                if guid_value and ifc_uris:
                    from_ifc = ifc_uris[0]  # use first IFC document declared in Index.rdf
                    create_directed_link(
                        g=g_links,
                        LS_ns=LS,
                        base_uri=base_uri,
                        from_document_uri=from_ifc,
                        to_document_uri=from_ifc,
                        sem_uri=ELS.HasPart,               # ISO semantic
                        structural_kind="Directed1toN",    # HasPart is 1→N
                        to_identifier={"kind": "string", "value": guid_value, "field": "GUID"},
                        note=None
                    )

    except Exception as e:
        messagebox.showerror("CSV Import Error", f"Error reading CSV: {e}")
        return

    # 7) Also process IfcProject: add a HasPart link for the root element if found
    if ifc_uris and ifcopenshell:
        for ifc_uri in ifc_uris:
            try:
                ifc_filename = None
                for s, p, o in g_index.triples((ifc_uri, CT.filename, None)):
                    ifc_filename = str(o).strip()
                    break
                if ifc_filename:
                    full_ifc_path = os.path.join(container_dir, "Payload documents", os.path.normpath(ifc_filename))
                    logger.info(f"Processing IfcProject in IFC file: {full_ifc_path}")
                    if os.path.exists(full_ifc_path):
                        ifc_file = ifcopenshell.open(full_ifc_path)
                        projects = ifc_file.by_type("IfcProject")
                        if projects:
                            ifc_project = projects[0]
                            logger.info(f"Found IfcProject with GlobalId: {ifc_project.GlobalId} in {ifc_filename}")

                            # HasPart inside IFC (1→N), anchor IfcProject by GUID on TO-end
                            create_directed_link(
                                g=g_links,
                                LS_ns=LS,
                                base_uri=base_uri,
                                from_document_uri=ifc_uri,
                                to_document_uri=ifc_uri,
                                sem_uri=ELS.HasPart,
                                structural_kind="Directed1toN",
                                to_identifier={"kind": "string", "value": ifc_project.GlobalId, "field": "GUID"},
                                note=None
                            )
                        else:
                            logger.info(f"IfcProject not found in IFC file: {ifc_filename}")
            except Exception as e:
                logger.error(f"Error processing IfcProject from IFC file: {e}")

    # 8) Save the new Link file in "Payload triples"
    payload_triplets_path = os.path.join(container_dir, "Payload triples")
    os.makedirs(payload_triplets_path, exist_ok=True)
    linkset_filename = f"LinksetRelations_{uuid.uuid4()}.rdf"
    linkset_filepath = os.path.join(payload_triplets_path, linkset_filename)
    g_links.serialize(destination=linkset_filepath, format="pretty-xml")
    logger.info(f"Link file saved: {linkset_filepath}")

    # 9) Update Index.rdf with a link to that link file
    linkset_file_ref = f"{base_uri}/Payload%20triples/{linkset_filename}"
    g_index.add((container_uri, CT.containsLinkset, URIRef(linkset_file_ref)))
    g_index.serialize(destination=index_path, format='pretty-xml')
    logger.info("Index.rdf updated with CSV/IFC links (ISO-only).")

    # 10) If ask_save=True => repack (standalone mode)
    if ask_save:
        updated_icdd_path = filedialog.asksaveasfilename(
            title="Save updated ICDD",
            defaultextension=".icdd",
            filetypes=[("ICDD files", "*.icdd")]
        )
        if updated_icdd_path:
            shutil.make_archive(container_dir, 'zip', container_dir)
            os.rename(f"{container_dir}.zip", updated_icdd_path)
            messagebox.showinfo("Success", f"Updated ICDD saved:\n{updated_icdd_path}")
            logger.info(f"Updated ICDD saved: {updated_icdd_path}")
        else:
            messagebox.showwarning("Saving", "No new ICDD file selected.")

    # 11) If we were in standalone mode (container_dir == icdd_temp_dir), remove temp
    if icdd_temp_dir and container_dir == icdd_temp_dir:
        shutil.rmtree(icdd_temp_dir, ignore_errors=True)
