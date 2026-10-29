# src/config.py
import os
from dotenv import load_dotenv

load_dotenv()

TB_HOST = os.getenv("TB_HOST", "http://localhost:8080")

# Cadência de envio
TARGET_EPS = int(os.getenv("TARGET_EPS", 20))

# Tipos de comunicação e prefixos de tokens
COMM_WIFI = "WiFi"
COMM_NBIOT = "NB-IoT"
COMM_LORA = "LoRa"

PREFIX_WIFI = "Sirius"
PREFIX_NBIOT = "00"
PREFIX_LORA = "SiriusLora"

# Arquivos de controle
CHECKPOINT_FILE = ".telix_checkpoints.json"