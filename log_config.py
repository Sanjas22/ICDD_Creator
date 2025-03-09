import logging
import os

def setup_logging():
    log_file = os.path.join(os.path.dirname(__file__), "icdd_tool.log")
    logging.basicConfig(
        level=logging.INFO,  # you can change it to DEBUG for a detailed log.
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
