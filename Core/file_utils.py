# Core/file_utils.py

import os
import shutil
import logging

logger = logging.getLogger(__name__)

def get_file_type(file_path):
    """
    Возвращает расширение файла в нижнем регистре.
    """
    _, ext = os.path.splitext(file_path)
    return ext.lower()

def remove_repeated_segments(rel_path):
    """
    It "collapses" consecutive repeating segments in a relative path.
    For Example: "CDE Backup_1/CDE Backup_1/folder" → "CDE Backup_1/folder"
    """
    norm = os.path.normpath(rel_path)
    parts = norm.split(os.sep)
    changed = True
    while changed:
        changed = False
        for i in range(len(parts) - 1):
            if parts[i] == parts[i+1]:
                del parts[i+1]
                changed = True
                break
    return os.path.join(*parts)

def flatten_double_cde_backup(cde_temp_dir):
    """
    Removes the subfolder "CDE Backup_1" (if exists) from CDE Backup.
    """
    outer = os.path.join(cde_temp_dir, "CDE Backup_1")
    inner = os.path.join(outer, "CDE Backup_1")
    if os.path.isdir(outer) and os.path.isdir(inner):
        for item in os.listdir(inner):
            src = os.path.join(inner, item)
            dst = os.path.join(outer, item)
            shutil.move(src, dst)
        os.rmdir(inner)
        logger.info("Flattened nested 'CDE Backup_1' folder.")
    else:
        logger.info("No nested 'CDE Backup_1' folder found.")

def make_icdd_archive(source_dir, destination_icdd_path):
    """
    Packages the contents of the source_dir directory into a ZIP archive and renames it to destination_icdd_path
    """
    archive_path = shutil.make_archive(source_dir, 'zip', source_dir)
    shutil.move(archive_path, destination_icdd_path)
