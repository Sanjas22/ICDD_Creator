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

# Если ifcopenshell установлен, импортируем его для обработки IFC
try:
    import ifcopenshell
except ImportError:
    ifcopenshell = None

from Core.rdf_utils import find_document_uri, generate_uri
from Core.file_utils import remove_repeated_segments

logger = logging.getLogger(__name__)


def process_csv_links():
    """
    Импортирует связи из CSV-файла в выбранный ICDD-контейнер.

    - Обрабатываются CSV-связи (с колонками fromPath, toPath, Type и опционально GUID).
    - Если в CSV указан GUID, дополнительно производится поиск объекта в IFC‑файлах,
      и создаётся запись (IfcPart) для этого объекта.
    - Отдельно, для каждого IFC-файла, если найден корневой элемент IfcProject, создаётся запись типа "IfcProject".

    Итоговый RDF-граф со связями сохраняется в папке "Payload triples", а Index.rdf обновляется.
    """
    # 1. Выбор ICDD-файла
    icdd_file_path = filedialog.askopenfilename(
        title="Выберите ICDD файл для обновления связей",
        filetypes=[("ICDD файлы", "*.icdd"), ("ZIP файлы", "*.zip"), ("Все файлы", "*.*")]
    )
    if not icdd_file_path:
        messagebox.showwarning("Ошибка", "Файл ICDD не выбран.")
        return

    icdd_temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(icdd_file_path, 'r') as zip_ref:
            zip_ref.extractall(icdd_temp_dir)
        logger.info(f"ICDD извлечён в {icdd_temp_dir}")
    except Exception as e:
        messagebox.showerror("Ошибка", f"Ошибка извлечения ICDD: {e}")
        shutil.rmtree(icdd_temp_dir)
        return

    # 2. Выбор CSV-файла со связями
    csv_file_path = filedialog.askopenfilename(
        title="Выберите CSV файл со связями",
        filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")]
    )
    if not csv_file_path:
        messagebox.showwarning("Ошибка", "CSV файл не выбран.")
        shutil.rmtree(icdd_temp_dir)
        return

    # 3. Загрузка Index.rdf
    index_path = os.path.join(icdd_temp_dir, 'Index.rdf')
    if not os.path.exists(index_path):
        messagebox.showerror("Ошибка", "Index.rdf не найден в контейнере.")
        shutil.rmtree(icdd_temp_dir)
        return

    g_index = Graph()
    try:
        g_index.parse(index_path)
    except Exception as e:
        messagebox.showerror("Ошибка", f"Ошибка парсинга Index.rdf: {e}")
        shutil.rmtree(icdd_temp_dir)
        return

    CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
    container_uri = None
    for s, p, o in g_index.triples((None, RDF.type, CT.ContainerDescription)):
        container_uri = s
        break
    if container_uri is None:
        messagebox.showerror("Ошибка", "ContainerDescription не найден в Index.rdf")
        shutil.rmtree(icdd_temp_dir)
        return

    base_uri = str(container_uri).rsplit("/", 1)[0]
    logger.debug(f"Базовый URI: {base_uri}")

    # 4. Поиск всех IFC-файлов в Index.rdf (с filetype, содержащим ".ifc")
    ifc_uris = []
    for s, p, o in g_index.triples((None, CT.filetype, None)):
        if ".ifc" in str(o).strip().lower():
            ifc_uris.append(s)
    if ifc_uris:
        logger.info(f"Найдено IFC документов: {len(ifc_uris)}")
    else:
        logger.info("IFC файлы не найдены в Index.rdf.")

    # 5. Построение объединённого словаря для IFC-объектов из всех IFC-файлов
    ifc_objects_dict = {}
    if ifc_uris and ifcopenshell:
        for ifc_uri in ifc_uris:
            ifc_filename = None
            for s, p, o in g_index.triples((ifc_uri, CT.filename, None)):
                ifc_filename = str(o).strip()
                break
            if ifc_filename:
                ifc_full_path = os.path.join(icdd_temp_dir, "Payload documents", os.path.normpath(ifc_filename))
                logger.info(f"IFC full path: {ifc_full_path}")
                if not os.path.exists(ifc_full_path):
                    logger.error(f"IFC файл не найден по пути: {ifc_full_path}")
                else:
                    try:
                        ifc_file = ifcopenshell.open(ifc_full_path)
                        # Сначала пробуем получить IfcWall; если их нет, получаем IfcProduct
                        objs = ifc_file.by_type("IfcWall")
                        if len(objs) == 0:
                            logger.info("Объекты типа IfcWall не найдены, пробуем IfcProduct.")
                            objs = ifc_file.by_type("IfcProduct")
                        for obj in objs:
                            if hasattr(obj, "GlobalId"):
                                ifc_objects_dict[obj.GlobalId] = obj
                        logger.info(f"Из IFC файла {ifc_filename} загружено объектов: {len(ifc_objects_dict)}")
                    except Exception as e:
                        logger.error(f"Ошибка обработки IFC файла {ifc_filename}: {e}")
    else:
        if not ifcopenshell:
            logger.warning("IfcOpenShell не установлен – автоматическая обработка IFC не выполняется.")

    # 6. Создание нового RDF графа для связей
    g_links = Graph()
    g_links.bind("ct", CT)
    LS = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset#")
    g_links.bind("ls", LS)
    g_links.bind("owl", "http://www.w3.org/2002/07/owl#")
    g_links.bind("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")

    # 7. Обработка CSV-связей (записи из CSV)
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
            messagebox.showerror("CSV Error", f"CSV файл должен содержать колонки: {', '.join(required_columns)}")
            shutil.rmtree(icdd_temp_dir)
            return

        for row in reader:
            from_path = row["fromPath"].strip().lstrip("\\/").replace("\\", "/")
            to_path = row["toPath"].strip().lstrip("\\/").replace("\\", "/")
            relation_type = row["Type"].strip()

            from_uri = find_document_uri(g_index, CT, from_path)
            to_uri = find_document_uri(g_index, CT, to_path)
            if not from_uri or not to_uri:
                logger.warning(f"Документы не найдены для путей: {from_path} или {to_path}")
                continue

            linkset_uri = generate_uri(base_uri, "Linkset")
            g_links.add((linkset_uri, RDF.type, LS.Linkset))
            g_links.add((linkset_uri, LS.hasFromLinkElement, from_uri))
            g_links.add((linkset_uri, LS.hasToLinkElement, to_uri))
            g_links.add((linkset_uri, LS.relationType, Literal(relation_type, datatype=XSD.string)))

            if "GUID" in row and row["GUID"].strip():
                guid_value = row["GUID"].strip()
                identifier_uri = generate_uri(base_uri, "StringBasedIdentifier")
                g_links.add((identifier_uri, LS.identifierField, Literal("GUID", datatype=XSD.string)))
                g_links.add((identifier_uri, LS.identifier, Literal(guid_value, datatype=XSD.string)))
                g_links.add((linkset_uri, LS.hasIdentifier, identifier_uri))

            # Если GUID указан и IFC объект найден, добавляем запись для этого объекта (IfcPart)
            if "GUID" in row and row["GUID"].strip() and ifc_objects_dict:
                guid_value = row["GUID"].strip()
                if guid_value in ifc_objects_dict:
                    logger.info(f"Найден IFC объект с GUID: {guid_value}")
                    component_uri = URIRef(f"{base_uri}/IfcComponent_{guid_value}")
                    ifc_linkset_uri = generate_uri(base_uri, "Linkset")
                    g_links.add((ifc_linkset_uri, RDF.type, LS.Linkset))
                    # Используем URI первого найденного IFC файла для ls:hasFromLinkElement
                    g_links.add((ifc_linkset_uri, LS.hasFromLinkElement, ifc_uris[0]))
                    g_links.add((ifc_linkset_uri, LS.hasToLinkElement, component_uri))
                    g_links.add((ifc_linkset_uri, LS.relationType, Literal("IfcPart", datatype=XSD.string)))
                    identifier_uri = generate_uri(base_uri, "StringBasedIdentifier")
                    g_links.add((identifier_uri, LS.identifierField, Literal("GUID", datatype=XSD.string)))
                    g_links.add((identifier_uri, LS.identifier, Literal(guid_value, datatype=XSD.string)))
                    g_links.add((ifc_linkset_uri, LS.hasIdentifier, identifier_uri))
                else:
                    logger.warning(f"IFC объект с GUID {guid_value} не найден в IFC файле.")

    # 8. Обработка IfcProject: добавляем запись для корневого элемента, если найден
    if ifc_uris and ifcopenshell:
        for ifc_uri in ifc_uris:
            try:
                ifc_filename = None
                for s, p, o in g_index.triples((ifc_uri, CT.filename, None)):
                    ifc_filename = str(o).strip()
                    break
                if ifc_filename:
                    ifc_full_path = os.path.join(icdd_temp_dir, "Payload documents", os.path.normpath(ifc_filename))
                    logger.info(f"Processing IfcProject in IFC file: {ifc_full_path}")
                    if os.path.exists(ifc_full_path):
                        ifc_file = ifcopenshell.open(ifc_full_path)
                        projects = ifc_file.by_type("IfcProject")
                        if projects:
                            ifc_project = projects[0]
                            logger.info(f"Found IfcProject with GlobalId: {ifc_project.GlobalId} in {ifc_filename}")
                            project_uri = URIRef(f"{base_uri}/IfcProject_{ifc_project.GlobalId}")
                            linkset_uri = generate_uri(base_uri, "Linkset")
                            g_links.add((linkset_uri, RDF.type, LS.Linkset))
                            g_links.add((linkset_uri, LS.hasFromLinkElement, ifc_uri))
                            g_links.add((linkset_uri, LS.hasToLinkElement, project_uri))
                            g_links.add((linkset_uri, LS.relationType, Literal("IfcProject", datatype=XSD.string)))
                            identifier_uri = generate_uri(base_uri, "StringBasedIdentifier")
                            g_links.add((identifier_uri, LS.identifierField, Literal("GUID", datatype=XSD.string)))
                            g_links.add(
                                (identifier_uri, LS.identifier, Literal(ifc_project.GlobalId, datatype=XSD.string)))
                            g_links.add((linkset_uri, LS.hasIdentifier, identifier_uri))
                        else:
                            logger.info(f"IfcProject not found in IFC file {ifc_filename}.")
            except Exception as e:
                logger.error(f"Error processing IfcProject from IFC file: {e}")

    # 9. Saving the RDF graph with links in "Payload triples"
    payload_triplets_dir = os.path.join(icdd_temp_dir, "Payload triples")
    os.makedirs(payload_triplets_dir, exist_ok=True)
    linkset_filename = f"LinksetRelations_{uuid.uuid4()}.rdf"
    linkset_filepath = os.path.join(payload_triplets_dir, linkset_filename)
    g_links.serialize(destination=linkset_filepath, format="pretty-xml")
    logger.info(f"Link file saved: {linkset_filepath}")

    # 10. Updating Index.rdf: adding a link to the links file.
    linkset_file_ref = f"{base_uri}/Payload%20triples/{linkset_filename}"
    g_index.add((container_uri, CT.containsLinkset, URIRef(linkset_file_ref)))
    g_index.serialize(destination=index_path, format="pretty-xml")
    logger.info("Index.rdf updated with the link to the links file.")

    # 11. Repacking the updated container into a new ICDD file
    updated_icdd_path = filedialog.asksaveasfilename(
        title="Save the updated ICDD",
        defaultextension=".icdd",
        filetypes=[("ICDD files", "*.icdd")]
    )
    if not updated_icdd_path:
        messagebox.showwarning("Saving", "The new ICDD file is not selected. Operation cancelled.")
        shutil.rmtree(icdd_temp_dir)
        return

    shutil.make_archive(icdd_temp_dir, 'zip', icdd_temp_dir)
    os.rename(f"{icdd_temp_dir}.zip", updated_icdd_path)
    messagebox.showinfo("Success", f"Updated ICDD saved:\n{updated_icdd_path}")
    logger.info(f"Updated ICDD saved: {updated_icdd_path}")

    shutil.rmtree(icdd_temp_dir, ignore_errors=True)


if __name__ == "__main__":
    process_csv_links()
