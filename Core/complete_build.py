import csv
import os
import zipfile
import tempfile
import shutil
import uuid
import logging
from tkinter import simpledialog, filedialog, messagebox
from rdflib import Graph, Namespace, RDF, Literal, XSD, URIRef

from Core.file_utils import remove_repeated_segments, flatten_double_cde_backup, make_icdd_archive
from Core.rdf_utils import generate_uri, find_document_uri

try:
    import ifcopenshell
except ImportError:
    ifcopenshell = None

logger = logging.getLogger(__name__)


def build_complete_icdd():
    """
    Объединённая операция для создания ICDD:
      1. Запрос базовых данных (Base URI, имя контейнера, издателя).
      2. Создание базового ICDD-контейнера (структура, Index.rdf, копирование онтологий).
      3. Импорт CDE Backup (по желанию) – копирование файлов в "Payload documents" и обновление Index.rdf.
      4. Импорт CSV/IFC связей (по желанию) – обработка CSV-файла, автоматическая обработка IFC-связей
         (добавление записи для корневого элемента IfcProject и для IFC-объектов по GUID).
      5. Перепаковка контейнера в новый ICDD-файл.
    """
    # --- Шаг 1: Сбор базовых данных ---
    base_uri = simpledialog.askstring("Input", "Введите Base URI:", initialvalue="http://example.com/container")
    if not base_uri:
        messagebox.showwarning("Create ICDD", "Base URI не указан.")
        return
    publisher_name = simpledialog.askstring("Input", "Введите имя издателя:")
    if not publisher_name:
        messagebox.showwarning("Create ICDD", "Имя издателя не указано.")
        return
    container_name = simpledialog.askstring("Input", "Введите имя ICDD контейнера:")
    if not container_name:
        messagebox.showwarning("Create ICDD", "Имя контейнера не указано.")
        return
    folder = filedialog.askdirectory(title="Выберите папку для создания ICDD")
    if not folder:
        messagebox.showwarning("Create ICDD", "Папка не выбрана.")
        return

    container_dir = os.path.join(folder, container_name)
    os.makedirs(container_dir, exist_ok=True)
    # Создаем поддиректории
    for sub in ['Ontology resources', 'Payload documents', 'Payload triples']:
        os.makedirs(os.path.join(container_dir, sub), exist_ok=True)

    # --- Шаг 2: Создание базового контейнера ---
    local_ontologies_path = os.path.join(os.path.dirname(__file__), '..', 'local_ontologies')
    ontologies = ['Container.rdf', 'Linkset.rdf', 'ExtendedLinkset.rdf']
    for filename in ontologies:
        src = os.path.join(local_ontologies_path, filename)
        dst = os.path.join(container_dir, 'Ontology resources', filename)
        if os.path.exists(src):
            shutil.copy(src, dst)
            logger.debug(f"Скопирована онтология: {filename}")
        else:
            messagebox.showerror("Ontology Error", f"{filename} не найдена.")

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
    index_path = os.path.join(container_dir, "Index.rdf")
    g.serialize(destination=index_path, format='pretty-xml')
    logger.info(f"Index.rdf создан в {index_path}")

    # --- Шаг 3: Импорт CDE Backup (по желанию) ---
    if messagebox.askyesno("CDE Backup", "Вы хотите импортировать CDE Backup в этот контейнер?"):
        import_cde_backup_complete(container_dir)

    # --- Шаг 4: Импорт CSV/IFC связей (по желанию) ---
    if messagebox.askyesno("CSV/IFC Links", "Вы хотите импортировать CSV/IFC связи?"):
        import_csv_links_complete(container_dir)

    # --- Шаг 5: Перепаковка контейнера ---
    updated_icdd_path = filedialog.asksaveasfilename(
        title="Сохраните готовый ICDD контейнер",
        defaultextension=".icdd",
        filetypes=[("ICDD файлы", "*.icdd")]
    )
    if not updated_icdd_path:
        messagebox.showwarning("Сохранение", "Файл не выбран, операция отменена.")
        return
    shutil.make_archive(container_dir, 'zip', container_dir)
    os.rename(f"{container_dir}.zip", updated_icdd_path)
    messagebox.showinfo("Успех", f"Готовый ICDD контейнер сохранён: {updated_icdd_path}")
    logger.info(f"Готовый ICDD контейнер сохранён: {updated_icdd_path}")


def import_cde_backup_complete(container_dir):
    """
    Импортирует CDE Backup в уже созданный контейнер (container_dir).
    """
    payload_documents_path = os.path.join(container_dir, "Payload documents")
    cde_backup_path = filedialog.askopenfilename(
        title="Выберите CDE Backup файл",
        filetypes=[("ZIP файлы", "*.zip"), ("Все файлы", "*.*")]
    )
    if not cde_backup_path:
        messagebox.showwarning("CDE Backup", "Файл CDE Backup не выбран.")
        return
    cde_temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cde_backup_path, 'r') as zip_ref:
            zip_ref.extractall(cde_temp_dir)
        logger.info(f"CDE Backup извлечён в {cde_temp_dir}")
        flatten_double_cde_backup(cde_temp_dir)
        messagebox.showinfo("Select Folders",
                            "Выберите папки для копирования из CDE Backup. Нажмите 'Отмена', когда закончите.")
        selected_folders = []
        while True:
            folder_path = filedialog.askdirectory(title="Выберите папку из CDE Backup", initialdir=cde_temp_dir)
            if not folder_path:
                break
            selected_folders.append(os.path.abspath(folder_path))
        selected_files = filedialog.askopenfilenames(title="Выберите файлы из CDE Backup", initialdir=cde_temp_dir)
        for folder in selected_folders:
            rel = remove_repeated_segments(os.path.relpath(folder, cde_temp_dir)).replace("\\", "/")
            dest = os.path.join(payload_documents_path, rel)
            shutil.copytree(folder, dest, dirs_exist_ok=True)
        for file in selected_files:
            rel = remove_repeated_segments(os.path.relpath(file, cde_temp_dir)).replace("\\", "/")
            dest = os.path.join(payload_documents_path, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(file, dest)
        # Обновляем Index.rdf (без создания Linkset)
        index_path = os.path.join(container_dir, "Index.rdf")
        g = Graph()
        g.parse(index_path)
        CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
        container_uri = None
        for s, p, o in g.triples((None, RDF.type, CT.ContainerDescription)):
            container_uri = s
            break
        if container_uri:
            from Core.rdf_utils import add_documents_flat
            add_documents_flat(g, CT, container_uri, container_uri.rsplit("/", 1)[0], payload_documents_path)
            g.serialize(destination=index_path, format='pretty-xml')
            logger.info("Index.rdf обновлён после импорта CDE Backup.")
    except Exception as e:
        messagebox.showerror("CDE Backup Error", f"Ошибка импорта CDE Backup: {e}")
        logger.error(f"Ошибка импорта CDE Backup: {e}")
    finally:
        shutil.rmtree(cde_temp_dir, ignore_errors=True)


def import_csv_links_complete(container_dir):
    """
    Импортирует CSV/IFC связи в уже созданный контейнер (container_dir).
    """
    csv_file_path = filedialog.askopenfilename(
        title="Выберите CSV файл со связями",
        filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")]
    )
    if not csv_file_path:
        messagebox.showwarning("CSV Import", "CSV файл не выбран.")
        return

    index_path = os.path.join(container_dir, "Index.rdf")
    if not os.path.exists(index_path):
        messagebox.showerror("Ошибка", "Index.rdf не найден в контейнере.")
        return

    g_index = Graph()
    try:
        g_index.parse(index_path)
    except Exception as e:
        messagebox.showerror("Ошибка", f"Ошибка парсинга Index.rdf: {e}")
        return

    CT = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Container#")
    container_uri = None
    for s, p, o in g_index.triples((None, RDF.type, CT.ContainerDescription)):
        container_uri = s
        break
    if container_uri is None:
        messagebox.showerror("Ошибка", "ContainerDescription не найден в Index.rdf")
        return

    base_uri = str(container_uri).rsplit("/", 1)[0]
    logger.debug(f"Базовый URI: {base_uri}")

    # Поиск всех IFC файлов в Index.rdf
    ifc_uris = []
    for s, p, o in g_index.triples((None, CT.filetype, None)):
        if ".ifc" in str(o).strip().lower():
            ifc_uris.append(s)
    if ifc_uris:
        logger.info(f"Найдено IFC документов: {len(ifc_uris)}")
    else:
        logger.info("IFC файлы не найдены в Index.rdf.")

    # Построение словаря IFC объектов
    ifc_objects_dict = {}
    if ifc_uris and ifcopenshell:
        for ifc_uri in ifc_uris:
            ifc_filename = None
            for s, p, o in g_index.triples((ifc_uri, CT.filename, None)):
                ifc_filename = str(o).strip()
                break
            if ifc_filename:
                ifc_full_path = os.path.join(container_dir, "Payload documents", os.path.normpath(ifc_filename))
                logger.info(f"IFC full path: {ifc_full_path}")
                if not os.path.exists(ifc_full_path):
                    logger.error(f"IFC файл не найден по пути: {ifc_full_path}")
                else:
                    try:
                        ifc_file = ifcopenshell.open(ifc_full_path)
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

    # Создание нового RDF графа для связей
    g_links = Graph()
    g_links.bind("ct", CT)
    LS = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset#")
    g_links.bind("ls", LS)
    g_links.bind("owl", "http://www.w3.org/2002/07/owl#")
    g_links.bind("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")

    # Обработка CSV-связей
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

            # Если GUID указан и IFC объект найден, добавляем запись для него (IfcPart)
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

    # Обработка IfcProject: добавляем запись для корневого элемента, если найден
    if ifc_uris and ifcopenshell:
        for ifc_uri in ifc_uris:
            try:
                ifc_filename = None
                for s, p, o in g_index.triples((ifc_uri, CT.filename, None)):
                    ifc_filename = str(o).strip()
                    break
                if ifc_filename:
                    ifc_full_path = os.path.join(container_dir, "Payload documents", os.path.normpath(ifc_filename))
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

    # Сохранение RDF графа со связями в папку "Payload triples"
    payload_triplets_dir = os.path.join(container_dir, "Payload triples")
    os.makedirs(payload_triplets_dir, exist_ok=True)
    linkset_filename = f"LinksetRelations_{uuid.uuid4()}.rdf"
    linkset_filepath = os.path.join(payload_triplets_dir, linkset_filename)
    g_links.serialize(destination=linkset_filepath, format="pretty-xml")
    logger.info(f"Link file saved: {linkset_filepath}")

    # Обновление Index.rdf: добавление ссылки на файл связей.
    linkset_file_ref = f"{base_uri}/Payload%20triples/{linkset_filename}"
    g_index.add((container_uri, CT.containsLinkset, URIRef(linkset_file_ref)))
    g_index.serialize(destination=index_path, format="pretty-xml")
    logger.info("Index.rdf updated with the link to the links file.")

    # Перепаковка контейнера в новый ICDD файл
    updated_icdd_path = filedialog.asksaveasfilename(
        title="Сохраните обновленный ICDD",
        defaultextension=".icdd",
        filetypes=[("ICDD файлы", "*.icdd")]
    )
    if not updated_icdd_path:
        messagebox.showwarning("Saving", "Новый ICDD файл не выбран. Operation cancelled.")
        shutil.rmtree(container_dir)
        return

    shutil.make_archive(container_dir, 'zip', container_dir)
    os.rename(f"{container_dir}.zip", updated_icdd_path)
    messagebox.showinfo("Success", f"Updated ICDD saved:\n{updated_icdd_path}")
    logger.info(f"Updated ICDD saved: {updated_icdd_path}")

    shutil.rmtree(container_dir, ignore_errors=True)


if __name__ == "__main__":
    build_complete_icdd()
