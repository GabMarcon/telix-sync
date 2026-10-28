import os
import re
import json
import pandas as pd
from datetime import datetime
from src.config import COMM_WIFI, COMM_NBIOT, PREFIX_WIFI, PREFIX_NBIOT
from src.core.logger import get_logger

log = get_logger()


def guess_serial_from_filename(filepath: str) -> str:
    """
    Tenta extrair o número de série automaticamente do nome do arquivo APENAS
    se seguir o padrão explícito 'SiriusXXX' ou 'convertido_ Token_'.
    Se o equipamento tiver nomenclatura customizada (ex: 'DL-12'), retorna vazio
    para evitar preenchimento incorreto e forçar a conferência do analista.
    """
    filename = os.path.basename(filepath)

    # Caso 1: Arquivo que já passou pelo conversor antes (ex: convertido_00762_...)
    match_conv = re.match(r'^convertido_(?:SiriusLora|Sirius|00)(\d+)_', filename, re.IGNORECASE)
    if match_conv:
        return match_conv.group(1)

    # Caso 2: Arquivo padrão Sirius (ex: Sirius762 - 28_10_2026.csv ou Sirius_762.csv)
    match_sirius = re.match(r'^Sirius(?:Lora)?[\s_-]*(\d+)\b', filename, re.IGNORECASE)
    if match_sirius:
        return match_sirius.group(1)

    return ""


def _resolve_token(nome_arquivo: str, source_type: str, comm_type: str = None, serial: str = None) -> str:
    """
    Centraliza a regra de criação do Token para Andrômeda, Telix e Reprocessamento (DLQ).
    """
    base_name = os.path.splitext(nome_arquivo)[0]
    # Caso seja um arquivo de falhas, limpa o sufixo para tentar deduzir o nome original
    if base_name.upper().endswith("_FALHAS"):
        base_name = base_name[:-7]

    if source_type == "andromeda":
        return base_name

    # Para 'telix' ou 'dlq'
    serial_clean = (serial or "").strip()

    # Se for DLQ de um arquivo Andrômeda (ex: SiriusLora340_FALHAS.csv) e o campo série estiver vazio
    if source_type == "dlq" and not serial_clean and base_name.lower().startswith("siriuslora"):
        return base_name

    if not serial_clean:
        raise ValueError("O Nº de Série (ou Token) é obrigatório para processar este arquivo.")

    # Se o operador digitou um token completo manualmente (ex: SiriusLora300 ou Sirius300), respeita
    if serial_clean.lower().startswith("sirius") or (serial_clean.startswith("00") and len(serial_clean) > 4):
        return serial_clean

    if comm_type == COMM_WIFI:
        return f"{PREFIX_WIFI}{serial_clean}"
    elif comm_type == COMM_NBIOT:
        return f"{PREFIX_NBIOT}{serial_clean}"
    else:
        raise ValueError("Tipo de comunicação inválido (selecione WiFi ou NB-IoT).")


def _convert_dates_to_ts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converte a coluna 'Data/Hora' para Epoch (ms) no fuso America/Sao_Paulo,
    removendo com segurança linhas vazias ou corrompidas antes de converter para int64.
    """
    if 'Data/Hora' not in df.columns:
        return df

    datas = pd.to_datetime(df['Data/Hora'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
    df = df[datas.notna()].copy()
    if df.empty:
        return df

    datas_validas = datas.dropna().dt.tz_localize('America/Sao_Paulo', ambiguous='NaT', nonexistent='NaT')
    df = df[datas_validas.notna()].copy()
    df['ts'] = datas_validas.dropna().astype('int64') // 10 ** 6
    return df


def _extract_dlq_payloads(file_path: str, max_rows: int = None) -> list:
    """
    Lê um arquivo _FALHAS.csv (Dead-Letter Queue) e reconstrói a lista de payloads JSON
    pronta para reenvio, sem passar pelo ETL tradicional.
    """
    payloads = []
    with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line or (idx == 0 and line.startswith("PAYLOAD_JSON")):
                continue

            parts = line.split(';', 1)
            raw_json = parts[0].strip()

            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError:
                # Retrocompatibilidade com arquivos antigos onde ',' foi trocada por '|'
                payload = json.loads(raw_json.replace('|', ','))

            if isinstance(payload, dict) and 'ts' in payload and 'values' in payload:
                payloads.append(payload)

            if max_rows and len(payloads) >= max_rows:
                break

    return payloads


def process_data(file_path: str, source_type: str, comm_type: str = None, serial: str = None):
    """
    Roteia o processamento com base na origem ('andromeda', 'telix' ou 'dlq').
    Retorna a lista de payloads estruturada e o Token de acesso gerado.
    """
    try:
        nome_arquivo = os.path.basename(file_path)
        token = _resolve_token(nome_arquivo, source_type, comm_type, serial)

        # 1. Rota de Reprocessamento de Falhas (DLQ)
        if source_type == "dlq":
            payloads = _extract_dlq_payloads(file_path)
            log.info(f"Origem DLQ (Reprocessamento). {len(payloads)} pacotes recuperados para o token: {token}")
            return payloads, token

        # 2. Rota Concentrador Andrômeda
        elif source_type == "andromeda":
            df = pd.read_csv(file_path, sep=',', encoding='utf-8')
            df = _convert_dates_to_ts(df)
            log.info(f"Origem Andrômeda. Token extraído: {token}")

        # 3. Rota Plataforma Telix (WiFi / NB-IoT)
        else:
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0)
            df = _apply_etl_rules(df_raw, nome_arquivo)

            output_dir = os.path.dirname(file_path)
            output_filename = f"convertido_{token}_{nome_arquivo}"

            # Salva o CSV sem a coluna 'ts' para manter cabeçalho 100% idêntico ao Andrômeda
            df_para_salvar = df.drop(columns=['ts'], errors='ignore')
            df_para_salvar.to_csv(os.path.join(output_dir, output_filename), index=False, sep=',', encoding='utf-8')

            log.info(f"Origem Telix. ETL aplicado e arquivo convertido salvo. Token gerado: {token}")

        return _validate_and_build_payloads(df), token

    except Exception as e:
        log.error(f"Erro no ETL ({os.path.basename(file_path)}): {str(e)}")
        raise e


def preview_data(file_path: str, source_type: str, comm_type: str = None, serial: str = None):
    """
    Executa um Dry-Run nas 3 primeiras linhas para visualização do Payload na interface (sem salvar arquivos).
    """
    try:
        nome_arquivo = os.path.basename(file_path)

        if source_type == "dlq":
            return _extract_dlq_payloads(file_path, max_rows=3)
        elif source_type == "andromeda":
            df = pd.read_csv(file_path, sep=',', encoding='utf-8', nrows=3)
            df = _convert_dates_to_ts(df)
        else:
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0, nrows=3)
            df = _apply_etl_rules(df_raw, nome_arquivo)

        return _validate_and_build_payloads(df)

    except Exception as e:
        log.error(f"Erro ao gerar preview de {os.path.basename(file_path)}: {str(e)}")
        raise e


def _apply_etl_rules(df: pd.DataFrame, nome_arquivo: str) -> pd.DataFrame:
    """
    Aplica a lógica de ETL em arquivos baixados do Telix, gerando o DataFrame
    com as colunas formatadas no padrão exato do Andrômeda.
    """
    if df.shape[1] < 13:
        raise ValueError(f"Arquivo {nome_arquivo} possui {df.shape[1]} colunas (esperado 13+). Dados incompletos.")

    df_saida = pd.DataFrame()
    datas_limpas = df.iloc[:, 1].fillna('').astype(str).str.replace(',', '').str.strip()

    def formatar_data(val):
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(val, fmt).strftime('%d/%m/%Y %H:%M:%S')
            except ValueError:
                pass
        return val

    df_saida['Data/Hora'] = datas_limpas.apply(formatar_data)

    nomes_sensores = ['s1d1', 's1d2', 's2d1', 's2d2', 's3d1', 's3d2', 's4d1', 's4d2']
    for i, nome in enumerate(nomes_sensores):
        df_saida[nome] = df.iloc[:, i + 2].fillna('').astype(str).str.replace(',', '.').str.strip().replace('nan', '')

    # Leitura fiel de lbat (coluna 10) e vbat (coluna 11) sem forçar 0.0 em campos vazios
    lbat_raw = df.iloc[:, 10].fillna('').astype(str).str.strip().str.lower()
    baterias_raw = df.iloc[:, 11].fillna('').astype(str).str.replace(',', '.').str.strip()
    baterias_num = pd.to_numeric(baterias_raw, errors='coerce')

    df_saida['Bateria (V)'] = baterias_num.apply(lambda x: f"{x:.3f}" if pd.notna(x) else '')

    def definir_bat_fraca(idx):
        val_lbat = lbat_raw.iloc[idx]
        if val_lbat in ('true', '1'):
            return 'True'
        if val_lbat in ('false', '0'):
            return 'False'
        val_vbat = baterias_num.iloc[idx]
        if pd.notna(val_vbat):
            return 'True' if val_vbat < 3.1 else 'False'
        return ''

    df_saida['Bat Fraca'] = [definir_bat_fraca(i) for i in range(len(df))]

    rssi_raw = df.iloc[:, 12].fillna('').astype(str).str.strip().replace('nan', '')
    df_saida['RSSI'] = rssi_raw
    df_saida['SNR'] = ''
    df_saida['Inserido'] = df_saida['Data/Hora']

    df_saida = _convert_dates_to_ts(df_saida)

    return df_saida


def _validate_and_build_payloads(df: pd.DataFrame) -> list:
    """
    Monta a lista de pacotes JSON garantindo que as chaves da API (timeseries)
    sejam exatamente as exigidas pela Rule Chain do Telix.
    """
    if df.empty:
        return []

    valid_payloads = []

    def to_float(val):
        try:
            if pd.isna(val):
                return None
            s = str(val).strip()
            if s == '' or s.lower() == 'nan':
                return None
            return float(s)
        except Exception:
            return None

    for row_dict in df.to_dict(orient='records'):
        if 'ts' not in row_dict or pd.isna(row_dict['ts']):
            continue

        ts_val = int(row_dict['ts'])
        values = {}

        for s in ('s1d1', 's1d2', 's2d1', 's2d2', 's3d1', 's3d2', 's4d1', 's4d2'):
            val = to_float(row_dict.get(s))
            if val is not None:
                values[s] = val

        vbat = to_float(row_dict.get('Bateria (V)'))
        if vbat is not None:
            values['vbat'] = vbat

        lbat_str = str(row_dict.get('Bat Fraca', '')).strip().lower()
        if lbat_str == 'true':
            values['lbat'] = True
        elif lbat_str == 'false':
            values['lbat'] = False

        rssi = to_float(row_dict.get('RSSI'))
        if rssi is not None:
            values['rssi'] = rssi

        snr = to_float(row_dict.get('SNR'))
        if snr is not None:
            values['snr'] = snr

        if values:
            valid_payloads.append({
                "ts": ts_val,
                "values": values
            })

    return valid_payloads