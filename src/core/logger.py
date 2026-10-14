import logging
from logging.handlers import RotatingFileHandler
import os

if not os.path.exists('logs'):
    os.makedirs('logs')

logger = logging.getLogger("TelixInjector")
logger.setLevel(logging.INFO)

# File Handler com rotação (5MB max)
file_handler = RotatingFileHandler('logs/injector.log', maxBytes=5*1024*1024, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

def get_logger():
    return logger