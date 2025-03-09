import uuid
import os
import logging
from rdflib import Graph, URIRef, Literal, Namespace, RDF, XSD
from Core.file_utils import remove_repeated_segments, get_file_type

logger = logging.getLogger(__name__)


def generate_uri(base_uri, prefix):
    """
    Generates a unique URI with the specified prefix.
    For example: http://example.com/container/InternalDocument<uuid>
    """
    return URIRef(f"{base_uri}/{prefix}{uuid.uuid4()}")


def find_document_uri(g, CT, path_value):
    """
    Searches for the document URI in the RDF graph by relative path.
    First it searches by ct:filename, then by ct:foldername.
    """
    # Bringing the path to a single format
    path_value = path_value.replace("\\", "/")
    logger.debug(f"Searching for document with path: {path_value}")

    # Search by ct:filename
    for s, p, o in g.triples((None, CT.filename, None)):
        if str(o) == path_value:
            logger.info(f"Found document by ct:filename: {s}")
            return s

    # Search by ct:foldername
    for s, p, o in g.triples((None, CT.foldername, None)):
        if str(o) == path_value:
            logger.info(f"Found document by ct:foldername: {s}")
            return s

    logger.warning(f"Document with path '{path_value}' not found.")
    return None


def add_link_triples(g, from_uri, to_uri, link_type_info):
    """
    Adds RDF triplets for communication between two URIs.
   The link_type_info parameter is a dictionary containing:
      – "property": the main type of connection
      - "inverse": the reverse type of communication (if required)
    """
    if link_type_info.get("property"):
        g.add((from_uri, link_type_info["property"], to_uri))
    if link_type_info.get("inverse"):
        g.add((to_uri, link_type_info["inverse"], from_uri))


def add_documents_flat(g, CT, container_uri, base_uri, payload_documents_path):
    """
    Bypasses the payload_documents_path directory and adds all folders and files
    as child elements of container_uri.

    A FolderDocument element is created for each found subfolder, and an InternalDocument element is created for each file.
    """
    for root, dirs, files in os.walk(payload_documents_path):
        # If there is no payload documents in the root folder, then in the Document folder
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

        # Processing files in the current directory
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
