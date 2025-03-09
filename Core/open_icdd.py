import os
import zipfile
import tempfile
import shutil
from tkinter import filedialog, messagebox
import logging

logger = logging.getLogger(__name__)


def open_icdd():
    logger.info("Starting the ICDD...")
    file_path = filedialog.askopenfilename(
        title="Select the ICDD file",
        filetypes=[("ICDD files", "*.icdd"), ("ZIP files", "*.zip"), ("All files", "*.*")]
    )
    if not file_path:
        messagebox.showwarning("Open ICDD", "The file is not selected.")
        return

    # Creating a temporary directory for unpacking ICDD
    temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        logger.info(f"ICDD extracted in: {temp_dir}")

        # Open the Unzipped directory (Explorer opens on Windows)
        os.startfile(temp_dir)

        # Modal window: ask the user to click OK when he finishes working with files.
        messagebox.showinfo("Open ICDD", f"The contents of the ICDD are extracted in: {temp_dir}\n\n"
                                         "When you are done with the file, click OK to delete the temporary folder.")
    except Exception as e:
        logger.error(f"Error when opening ICDD: {e}")
        messagebox.showerror("Open ICDD", f"Error: {e}")
    finally:
        # After closing the dialog window, delete the temporary directory.
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"Temporary directory {temp_dir} deleted.")
        except Exception as e:
            logger.error(f"Error deleting a temporary directory {temp_dir}: {e}")


if __name__ == "__main__":
    open_icdd()
