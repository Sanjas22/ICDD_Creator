import uuid
import os
import logging
from typing import Optional, Dict, Tuple

from rdflib import Graph, URIRef, Literal, Namespace, RDF, RDFS, XSD

from Core.file_utils import remove_repeated_segments, get_file_type

logger = logging.getLogger(__name__)


# =============================================================================
# Basic container/file helpers (как было)
# =============================================================================

def generate_uri(base_uri, prefix) -> URIRef:
    """
    Generates a unique URI with the specified prefix.
    For example: http://example.com/container/InternalDocument<uuid>
    """
    return URIRef(f"{base_uri}/{prefix}{uuid.uuid4()}")


def find_document_uri(g: Graph, CT: Namespace, path_value: str) -> Optional[URIRef]:
    """
    Searches for the document URI in the RDF graph by relative path.
    First it searches by ct:filename, then by ct:foldername.
    """
    # Normalize slashes
    path_value = path_value.replace("\\", "/")
    logger.debug(f"Searching for document with path: {path_value}")

    # Search by ct:filename
    for s, _, o in g.triples((None, CT.filename, None)):
        if str(o) == path_value:
            logger.info(f"Found document by ct:filename: {s}")
            return s

    # Search by ct:foldername
    for s, _, o in g.triples((None, CT.foldername, None)):
        if str(o) == path_value:
            logger.info(f"Found document by ct:foldername: {s}")
            return s

    logger.warning(f"Document with path '{path_value}' not found.")
    return None


def add_documents_flat(g: Graph, CT: Namespace, container_uri: URIRef,
                       base_uri: str, payload_documents_path: str) -> None:
    """
    Walks the payload_documents_path directory and adds all folders and files
    as child elements of container_uri.

    For each subfolder -> ct:FolderDocument
    For each file     -> ct:InternalDocument
    """
    for root, dirs, files in os.walk(payload_documents_path):
        # Add folders (except the root itself)
        if os.path.abspath(root) != os.path.abspath(payload_documents_path):
            rel_folder = os.path.relpath(root, payload_documents_path)
            rel_folder = remove_repeated_segments(rel_folder).replace("\\", "/")
            folder_uri = generate_uri(base_uri, "FolderDocument")
            folder_name = os.path.basename(root)
            logger.debug(f"Creating FolderDocument for folder: {folder_name} with path: {rel_folder}")
            g.add((folder_uri, RDF.type, CT.FolderDocument))
            g.add((folder_uri, CT.foldername, Literal(rel_folder, datatype=XSD.string)))
            g.add((folder_uri, CT.name, Literal(folder_name, datatype=XSD.string)))
            g.add((container_uri, CT.containsDocument, folder_uri))

        # Add files in current directory
        for file in sorted(files):
            full_file_path = os.path.join(root, file)
            rel_file = os.path.relpath(full_file_path, payload_documents_path)
            rel_file = remove_repeated_segments(rel_file).replace("\\", "/")
            file_uri = generate_uri(base_uri, "InternalDocument")
            logger.debug(f"Creating InternalDocument for file: {file} with path: {rel_file}")
            g.add((file_uri, RDF.type, CT.InternalDocument))
            g.add((file_uri, CT.filetype, Literal(get_file_type(full_file_path), datatype=XSD.string)))
            g.add((file_uri, CT.filename, Literal(rel_file, datatype=XSD.string)))
            g.add((file_uri, CT.name, Literal(file, datatype=XSD.string)))
            g.add((container_uri, CT.containsDocument, file_uri))


# =============================================================================
# ISO 21597 Linkset helpers (Link / LinkElement / Identifiers)
# =============================================================================

def create_link_elements(g: Graph, LS: Namespace, base_uri: str,
                         from_document_uri: URIRef, to_document_uri: URIRef) -> Tuple[URIRef, URIRef]:
    """
    Create two ls:LinkElement individuals (FROM and TO) and attach ls:hasDocument to each.
    Returns (le_from_uri, le_to_uri).
    """
    le_from_uri = generate_uri(base_uri, "LinkElement_from")
    le_to_uri   = generate_uri(base_uri, "LinkElement_to")

    # FROM end
    g.add((le_from_uri, RDF.type, LS.LinkElement))
    g.add((le_from_uri, LS.hasDocument, from_document_uri))

    # TO end
    g.add((le_to_uri, RDF.type, LS.LinkElement))
    g.add((le_to_uri, LS.hasDocument, to_document_uri))

    return le_from_uri, le_to_uri


def attach_string_identifier(g: Graph, LS: Namespace, base_uri: str,
                             link_element_uri: URIRef, value: str, field: str = "GUID") -> URIRef:
    """
    Attach a StringBasedIdentifier to a LinkElement:
      <ls:hasIdentifier>
        <ls:StringBasedIdentifier>
          <ls:identifierField>...</ls:identifierField>
          <ls:identifier>...</ls:identifier>
    Returns the identifier node URI.
    """
    id_uri = generate_uri(base_uri, "StringBasedIdentifier")
    g.add((id_uri, RDF.type, LS.StringBasedIdentifier))
    g.add((id_uri, LS.identifierField, Literal(field, datatype=XSD.string)))
    g.add((id_uri, LS.identifier, Literal(value, datatype=XSD.string)))
    g.add((link_element_uri, LS.hasIdentifier, id_uri))
    return id_uri


def attach_uri_identifier(g: Graph, LS: Namespace, base_uri: str,
                          link_element_uri: URIRef, uri_value: str) -> URIRef:
    """
    Attach a URIBasedIdentifier to a LinkElement:
      <ls:hasIdentifier>
        <ls:URIBasedIdentifier>
          <ls:uri>...</ls:uri>
    """
    id_uri = generate_uri(base_uri, "URIBasedIdentifier")
    g.add((id_uri, RDF.type, LS.URIBasedIdentifier))
    g.add((id_uri, LS.uri, Literal(uri_value, datatype=XSD.anyURI)))
    g.add((link_element_uri, LS.hasIdentifier, id_uri))
    return id_uri


def attach_query_identifier(g: Graph, LS: Namespace, base_uri: str,
                            link_element_uri: URIRef, query_expression: str, query_language: str = "XPath") -> URIRef:
    """
    Attach a QueryBasedIdentifier to a LinkElement:
      <ls:hasIdentifier>
        <ls:QueryBasedIdentifier>
          <ls:queryLanguage>...</ls:queryLanguage>
          <ls:queryExpression>...</ls:queryExpression>
    """
    id_uri = generate_uri(base_uri, "QueryBasedIdentifier")
    g.add((id_uri, RDF.type, LS.QueryBasedIdentifier))
    g.add((id_uri, LS.queryLanguage, Literal(query_language, datatype=XSD.string)))
    g.add((id_uri, LS.queryExpression, Literal(query_expression, datatype=XSD.string)))
    g.add((link_element_uri, LS.hasIdentifier, id_uri))
    return id_uri


# =============================================================================
# ISO-only ontology reading + aliases (ExtendedLinkset)
# =============================================================================

LS  = Namespace("https://standards.iso.org/iso/21597/-1/ed-1/en/Linkset#")
ELS = Namespace("https://standards.iso.org/iso/21597/-2/ed-1/en/ExtendedLinkset#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")

# Небольшой алиас-словарь для «человеческих» CSV-типов → ISO имён (localName)
ALIASES: Dict[str, str] = {
    "elaboration": "elaborates",
    "elaborate": "elaborates",
    "control": "controls",
    "aggregation": "haspart",
    "aggregate": "haspart",
    "membership": "hasmember",
    "member": "hasmember",
    "specialization": "specialises",
    "specialisation": "specialises",
    "replacement": "supersedes",
    "identity": "isidenticalto",
    "alternative": "isalternativeto",
    "conflict": "conflictswith",
}


def _localname(u: URIRef) -> str:
    return str(u).split("#")[-1].lower()


def build_iso_semantics_index(extendedlinkset_rdf_path: str) -> Tuple[Dict[str, URIRef], Graph]:
    """
    Загружает ExtendedLinkset.rdf и строит индекс:
      - name_to_uri: {локальное имя (lower) или rdfs:label(lower) -> URI класса ELS:*}
      - также возвращает сам граф g_els для дальнейших проверок (subClassOf).
    Если файл не найден/не читается — вернёт (пустой индекс, пустой граф).
    """
    g_els = Graph()
    name_to_uri: Dict[str, URIRef] = {}

    try:
        g_els.parse(extendedlinkset_rdf_path)
    except Exception as e:
        logger.warning(f"Could not parse ExtendedLinkset at '{extendedlinkset_rdf_path}': {e}")
        return name_to_uri, g_els

    for c in g_els.subjects(RDF.type, OWL.Class):
        c = URIRef(c)
        if not str(c).startswith(str(ELS)):
            continue
        # локальное имя
        name_to_uri[_localname(c)] = c
        # метки (если присутствуют в онтологии)
        for lab in g_els.objects(c, RDFS.label):
            key = str(lab).strip().lower()
            if key:
                name_to_uri[key] = c

    return name_to_uri, g_els


def _is_subclass_of(g: Graph, child: URIRef, parent: URIRef) -> bool:
    """Транзитивная проверка rdfs:subClassOf."""
    seen = set()
    stack = [child]
    while stack:
        cur = stack.pop()
        if cur == parent:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        for sup in g.objects(cur, RDFS.subClassOf):
            if isinstance(sup, URIRef):
                stack.append(sup)
    return False


def normalize_csv_type_to_iso(
    relation_type_raw: str,
    name_to_uri: Dict[str, URIRef],
    g_els: Graph
) -> Tuple[Optional[URIRef], str]:
    """
    Превращает CSV-строку в (sem_uri, structural_kind), где:
      sem_uri ∈ ELS:* или None,
      structural_kind ∈ {"Directed1toN","DirectedBinary"}.
    Правила:
      - нормализуем строку (lower + удаляем пробелы/подчёркивания/дефисы);
      - применяем ALIASES;
      - ищем по индексу онтологии (localName/label);
      - если не нашли — возвращаем (None, "Directed1toN") как безопасный дефолт;
      - если нашли — структура бинарная, если класс подкласс ls:DirectedBinaryLink, иначе 1→N.
    """
    t = (relation_type_raw or "").strip().lower()
    if not t:
        return (None, "Directed1toN")

    t_norm = t.replace(" ", "").replace("_", "").replace("-", "")
    t_norm = ALIASES.get(t_norm, t_norm)

    sem = name_to_uri.get(t_norm)
    if sem is None:
        return (None, "Directed1toN")

    structural = "DirectedBinary" if _is_subclass_of(g_els, sem, LS.DirectedBinaryLink) else "Directed1toN"
    return (sem, structural)


# =============================================================================
# Link creation (ISO-only): ls:Link + structure + optional ELS sem.type
# =============================================================================

def create_directed_link(
    g: Graph,
    LS_ns: Namespace,
    base_uri: str,
    from_document_uri: URIRef,
    to_document_uri: URIRef,
    sem_uri: Optional[URIRef] = None,          # <- ELS:* семантика или None
    structural_kind: str = "Directed1toN",     # "Directed1toN" | "DirectedBinary"
    to_identifier: Optional[dict] = None,      # {"kind":"string"/"uri"/"query", ...}
    note: Optional[str] = None                 # rdfs:comment (например, Unmapped CSV Type)
) -> Dict[str, URIRef]:
    """
    Создаёт корректный ISO линк:
      - индивидуум ls:Link;
      - структурный тип: ls:Directed1toNLink или ls:DirectedBinaryLink (по аргументу);
      - при наличии sem_uri -> добавляем rdf:type ELS:*;
      - создаём 2 конца как ls:LinkElement с ls:hasDocument;
      - опционально вешаем идентификатор на TO-конец (String/URI/Query);
      - при note -> добавляем rdfs:comment.

    Возвращает словарь с URI созданных сущностей.
    """
    # 1) Сам линк
    link_uri = generate_uri(base_uri, "Link")
    g.add((link_uri, RDF.type, LS_ns.Link))

    # 2) Структура (Part 1)
    if structural_kind == "DirectedBinary":
        g.add((link_uri, RDF.type, LS_ns.DirectedBinaryLink))
    else:
        g.add((link_uri, RDF.type, LS_ns.Directed1toNLink))

    # 3) Семантика (Part 2) — если распознали
    if sem_uri is not None:
        g.add((link_uri, RDF.type, sem_uri))

    # 4) Концы
    le_from_uri, le_to_uri = create_link_elements(g, LS_ns, base_uri, from_document_uri, to_document_uri)
    g.add((link_uri, LS_ns.hasFromLinkElement, le_from_uri))
    g.add((link_uri, LS_ns.hasToLinkElement,   le_to_uri))

    # 5) Идентификатор на TO-конце (по желанию)
    if to_identifier:
        kind = (to_identifier.get("kind") or "").lower()
        if kind == "string" and to_identifier.get("value"):
            attach_string_identifier(
                g, LS_ns, base_uri, le_to_uri,
                value=to_identifier["value"],
                field=to_identifier.get("field") or "GUID"
            )
        elif kind == "uri" and to_identifier.get("uri"):
            attach_uri_identifier(g, LS_ns, base_uri, le_to_uri, uri_value=to_identifier["uri"])
        elif kind == "query" and to_identifier.get("expression"):
            attach_query_identifier(
                g, LS_ns, base_uri, le_to_uri,
                query_expression=to_identifier["expression"],
                query_language=to_identifier.get("language") or "XPath"
            )

    # 6) Примечание (если тип из CSV не распознан и т.п.)
    if note:
        g.add((link_uri, RDFS.comment, Literal(note, datatype=XSD.string)))

    return {"link": link_uri, "from": le_from_uri, "to": le_to_uri}
