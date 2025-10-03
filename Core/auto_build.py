# Core/auto_build.py

import os
import shutil
import uuid
import logging
import tempfile
import zipfile
import csv
from tkinter import simpledialog, filedialog, messagebox
from rdflib import Graph, Namespace, RDF, Literal, XSD, URIRef

from Core.file_utils import remove_repeated_segments, flatten_double_cde_backup
from Core.rdf_utils import (
    generate_uri,
    find_document_uri,
    create_directed_link,
    build_iso_semantics_index,
    normalize_csv_type_to_iso,
)

# Если IfcOpenShell установлен, импортируем его (не обязателен в этом сценарии)
try:
    import ifcopenshell
except ImportError:
    ifcopenshell = None

logger = logging.getLogger(__name__)


def build_icdd_auto_csv():
    """
    Объединённый сценарий создания ICDD контейнера (ISO-only):
      1) Запрос базовых данных (Base URI, Publisher, Container Name, целевая папка).
      2) Создание базовой структуры, Index.rdf, копирование онтологий (Container/Linkset/ExtendedLinkset).
      3) Обязательный импорт CDE Backup (ZIP) -> копирование выбранных папок/файлов в "Payload documents",
         обновление Index.rdf (ct:containsDocument + ct:filename/foldername).
      4) Авто-поиск CSV внутри распакованного CDE и импорт связей:
         - Каждая строка CSV (fromPath, toPath, Type [, GUID]) -> создаётся ls:Link
           с двумя ls:LinkElement и ls:hasDocument на концах;
         - Семантика берётся из ExtendedLinkset.rdf (els:*) через чтение онтологии + алиасы;
         - Структура выбирается автоматически (ls:Directed1toNLink / ls:DirectedBinaryLink);
         - Если тип не распознан -> создаётся корректный ISO-линк (1→N) + rdfs:comment с пометкой;
         - Если есть GUID и в Index.rdf присутствует IFC-документ, добавляется ISO-связь HasPart
           внутри IFC (оба конца указывают на IFC-документ, сам элемент задаётся идентификатором на TO-конце).
      5) Финальное сохранение контейнера в .icdd.
    """
    # --- Step 1: Collect basic data ---
    base_uri = simpledialog.askstring("Input", "Enter Base URI:", initialvalue="http://example.com/container")
    if not base_uri:
        messagebox.showwarning("Create ICDD", "Base URI not specified.")
        return

    publisher_name = simpledialog.askstring("Input", "Enter the publisher name:")
    if not publisher_name:
        messagebox.showwarning("Create ICDD", "Publisher name not specified.")
        return

    container_name = simpledialog.askstring("Input", "Enter the ICDD container name:")
    if not container_name:
        messagebox.showwarning("Create ICDD", "Container name not specified.")
        return

    folder = filedialog.askdirectory(title="Select the folder to create the ICDD")
    if not folder:
        messagebox.showwarning("Create ICDD", "No folder selected.")
        return

    # Создаём контейнер (container_dir)
    container_dir = os.path.join(folder, container_name)
    os.makedirs(container_dir, exist_ok=True)
    for sub in ['Ontology resources', 'Payload documents', 'Payload triples']:
        os.makedirs(os.path.join(container_dir, sub), exist_ok=True)

    # --- Step 2: Create the basic container (Index.rdf + ontologies) ---
    local_ontologies_path = os.path.join(os.path.dirname(__file__), '..', 'local_ontologies')
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

    g.add((container_uri, RDF.type, CT.ContainerDescription))
    g.add((
        container_uri,
        CT.conformanceIndicator,
        Literal("ICDD-Part1-Container", datatype=XSD.string)
    ))
    g.add((container_uri, CT.publishedBy, publisher_uri))
    g.add((publisher_uri, RDF.type, CT.Party))
    g.add((publisher_uri, CT.name, Literal(publisher_name, datatype=XSD.string)))

    ontology = URIRef(base_uri)
    g.add((ontology, RDF.type, OWL.Ontology))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-1/ed-1/en/Container.rdf")))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset.rdf")))
    g.add((ontology, OWL.imports, URIRef("https://standards.iso.org/iso/21597/-2/ed-1/en/ExtendedLinkset.rdf")))

    index_path = os.path.join(container_dir, "Index.rdf")
    g.serialize(destination=index_path, format='pretty-xml')
    logger.info(f"Index.rdf created at {index_path}")

    # --- Step 3: Import CDE Backup (mandatory) ---
    cde_backup_path = filedialog.askopenfilename(
        title="Select CDE Backup file (ZIP)",
        filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
    )
    if not cde_backup_path:
        messagebox.showwarning("CDE Backup", "No CDE Backup file selected.")
        return

    cde_temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cde_backup_path, 'r') as zip_ref:
            zip_ref.extractall(cde_temp_dir)
        logger.info(f"CDE Backup extracted into {cde_temp_dir}")

        flatten_double_cde_backup(cde_temp_dir)

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

        payload_docs = os.path.join(container_dir, "Payload documents")
        os.makedirs(payload_docs, exist_ok=True)

        for folder in selected_folders:
            rel = os.path.relpath(folder, cde_temp_dir).replace("\\", "/")
            shutil.copytree(folder, os.path.join(payload_docs, rel), dirs_exist_ok=True)

        for file in selected_files:
            rel = os.path.relpath(file, cde_temp_dir).replace("\\", "/")
            dest = os.path.join(payload_docs, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(file, dest)

        # Обновляем Index.rdf после импорта CDE Backup
        g_idx = Graph()
        g_idx.parse(index_path)
        container_uri_found = None
        for s, p, o in g_idx.triples((None, RDF.type, CT.ContainerDescription)):
            container_uri_found = s
            break
        if container_uri_found:
            from Core.rdf_utils import add_documents_flat
            base_uri_for_idx = str(container_uri_found).rsplit("/", 1)[0]
            add_documents_flat(g_idx, CT, container_uri_found, base_uri_for_idx, payload_docs)
            g_idx.serialize(destination=index_path, format='pretty-xml')
            logger.info("Index.rdf updated after CDE Backup import.")
    except Exception as e:
        messagebox.showerror("CDE Backup Error", f"Error importing CDE Backup: {e}")
        logger.error(f"Error importing CDE Backup: {e}")
        shutil.rmtree(cde_temp_dir, ignore_errors=True)
        return

    # --- Step 4: Auto-import CSV links from CDE Backup ---
    # Ищем CSV-файлы внутри cde_temp_dir
    csv_files = []
    for root, dirs, files in os.walk(cde_temp_dir):
        for f in files:
            if f.lower().endswith(".csv"):
                csv_files.append(os.path.join(root, f))

    if not csv_files:
        logger.info("No CSV files found in CDE Backup. Skipping CSV import.")
    else:
        logger.info(f"Found {len(csv_files)} CSV file(s) in CDE Backup. Auto-importing links.")
        g_idx_csv = Graph()
        g_idx_csv.parse(index_path)
        container_uri_csv = None
        for s, p, o in g_idx_csv.triples((None, RDF.type, CT.ContainerDescription)):
            container_uri_csv = s
            break
        base_uri_csv = str(container_uri_csv).rsplit("/", 1)[0] if container_uri_csv else base_uri

        # Граф для связей
        g_links = Graph()
        LS  = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset#")
        ELS = Namespace("https://standards.iso.org/iso/21597/-2/ed-1/en/ExtendedLinkset#")
        g_links.bind("ls", LS)
        g_links.bind("els", ELS)
        g_links.bind("owl", "http://www.w3.org/2002/07/owl#")
        g_links.bind("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
        g_links.bind("ct", CT)

        # Индекс семантик ISO (из онтологии в контейнере)
        els_path = os.path.join(container_dir, "Ontology resources", "ExtendedLinkset.rdf")
        name_to_uri, g_els = build_iso_semantics_index(els_path)
        if not name_to_uri:
            logger.warning("ExtendedLinkset index is empty. Semantic mapping will rely on aliases only; "
                           "unrecognized types will fall back to generic ls:Link + ls:Directed1toNLink.")

        # Собираем URI IFC документов из Index.rdf (без разбора объектов)
        ifc_uris = []
        for s, p, o in g_idx_csv.triples((None, CT.filetype, None)):
            if ".ifc" in str(o).strip().lower():
                ifc_uris.append(s)
        if ifc_uris:
            logger.info(f"IFC documents found in Index.rdf: {len(ifc_uris)}")
        else:
            logger.info("No IFC documents found in Index.rdf.")

        # Обрабатываем каждый CSV-файл
        for csv_path in csv_files:
            logger.info(f"Auto-processing CSV: {csv_path}")
            try:
                with open(csv_path, newline='', encoding='utf-8') as cf:
                    sample = cf.read(1024)
                    cf.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(sample)
                    except csv.Error:
                        dialect = csv.excel
                    reader = csv.DictReader(cf, delimiter=dialect.delimiter)
                    req_cols = {"fromPath", "toPath", "Type"}
                    if not req_cols.issubset(reader.fieldnames):
                        logger.warning(f"CSV {csv_path} missing required columns: {req_cols}")
                        continue

                    for row in reader:
                        from_path = row["fromPath"].strip().lstrip("\\/").replace("\\", "/")
                        to_path   = row["toPath"].strip().lstrip("\\/").replace("\\", "/")
                        rel_type  = (row["Type"] or "").strip()

                        from_uri = find_document_uri(g_idx_csv, CT, from_path)
                        to_uri   = find_document_uri(g_idx_csv, CT, to_path)
                        if not from_uri or not to_uri:
                            logger.warning(f"Documents not found for: {from_path} or {to_path}")
                            continue

                        # GUID на TO-конце (опционально)
                        guid_value = (row.get("GUID") or "").strip()
                        to_identifier = {"kind": "string", "value": guid_value, "field": "GUID"} if guid_value else None

                        # Маппинг CSV Type -> (ELS семантика, структурный тип)
                        sem_uri, structural_kind = normalize_csv_type_to_iso(rel_type, name_to_uri, g_els)
                        note = None
                        if sem_uri is None:
                            note = f"Unmapped CSV Type: '{rel_type}'"
                            logger.warning(note)

                        # Основная связь из CSV
                        create_directed_link(
                            g=g_links,
                            LS_ns=LS,
                            base_uri=base_uri_csv,
                            from_document_uri=from_uri,
                            to_document_uri=to_uri,
                            sem_uri=sem_uri,                  # ELS:* или None
                            structural_kind=structural_kind,  # "Directed1toN"/"DirectedBinary"
                            to_identifier=to_identifier,      # идентификатор на TO-конце (если есть GUID)
                            note=note
                        )

                        # Доп. связь HasPart (1→N) внутри IFC, если есть GUID и хотя бы один IFC-документ
                        if guid_value and ifc_uris:
                            from_ifc = ifc_uris[0]  # используем первый IFC-документ из Index.rdf
                            create_directed_link(
                                g=g_links,
                                LS_ns=LS,
                                base_uri=base_uri_csv,
                                from_document_uri=from_ifc,
                                to_document_uri=from_ifc,
                                sem_uri=ELS.HasPart,           # ISO семантика
                                structural_kind="Directed1toN",
                                to_identifier={"kind": "string", "value": guid_value, "field": "GUID"},
                                note=None
                            )
            except Exception as e:
                logger.error(f"Error reading auto CSV {csv_path}: {e}")

        # Сохраняем объединенный Link RDF
        payload_triplets = os.path.join(container_dir, "Payload triples")
        os.makedirs(payload_triplets, exist_ok=True)
        linkset_filename = f"LinksetRelations_{uuid.uuid4()}.rdf"
        linkset_path = os.path.join(payload_triplets, linkset_filename)
        g_links.serialize(destination=linkset_path, format="pretty-xml")
        logger.info(f"Auto CSV link file saved: {linkset_path}")

        # Обновляем Index.rdf (указывает на файл со связями)
        linkset_file_ref = f"{base_uri_csv}/Payload%20triples/{linkset_filename}"
        g_idx_csv.add((container_uri_csv, CT.containsLinkset, URIRef(linkset_file_ref)))
        g_idx_csv.serialize(destination=index_path, format='pretty-xml')
        logger.info("Index.rdf updated with auto CSV links.")
    # --- End auto CSV import ---

    # --- Step 5: Final save of the container ---
    updated_icdd_path = filedialog.asksaveasfilename(
        title="Save the final ICDD container (Auto CSV)",
        defaultextension=".icdd",
        filetypes=[("ICDD files", "*.icdd")]
    )
    if not updated_icdd_path:
        messagebox.showwarning("Saving", "No file selected, operation cancelled.")
        shutil.rmtree(cde_temp_dir, ignore_errors=True)
        return

    shutil.make_archive(container_dir, 'zip', container_dir)
    final_zip = f"{container_dir}.zip"
    os.rename(final_zip, updated_icdd_path)
    messagebox.showinfo("Success", f"The final ICDD container has been saved:\n{updated_icdd_path}")
    logger.info(f"The final ICDD container has been saved: {updated_icdd_path}")

    shutil.rmtree(cde_temp_dir, ignore_errors=True)


if __name__ == "__main__":
    build_icdd_auto_csv()
