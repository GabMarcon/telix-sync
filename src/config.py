# src/config.py
import os
from dotenv import load_dotenv

load_dotenv()

TB_HOST = os.getenv("TB_HOST", "http://localhost:8080")

# Cadência de envio
TARGET_EPS = int(os.getenv("TARGET_EPS", 20)) # Dispara 20 telemetrias por segundo por padrão

# Tipos de comunicação e tokens
COMM_WIFI = "WiFi"
COMM_NBIOT = "NB-IoT"
COMM_LORA = "LoRa (Andrômeda)"
PREFIX_WIFI = "Sirius"
PREFIX_NBIOT = "00"

# Arquivos de controle
CHECKPOINT_FILE = ".telix_checkpoints.json"