import os
import re
import json
import pandas as pd
from datetime import datetime
from src.config import (
    COMM_WIFI, COMM_NBIOT, COMM_LORA,
    PREFIX_WIFI, PREFIX_NBIOT, PREFIX_LORA
)
from src.core.logger import get_logger

log = get_logger()


def guess_serial_from_filename(filepath: str) -> str:
    """
    Tenta extrair o número de série automaticamente do nome do arquivo APENAS
    se começar explicitamente com 'SiriusXXX' ou 'convertido_Token_'.
    Se o arquivo vier como 'default_...' ou nome customizado ('DL-12'), retorna vazio
    para acionar o alerta visual na interface e exigir digitação manual.
    """
    filename = os.path.basename(filepath)

    # Caso 1: Arquivo que já passou pelo conversor antes (ex: convertido_SiriusLora727_...)
    match_conv = re.match(r'^convertido_(?:SiriusLora|Sirius|00)(\d+)_', filename, re.IGNORECASE)
    if match_conv:
        return match_conv.group(1)

    # Caso 2: Arquivo padrão Sirius (ex: Sirius727_11-11... ou Sirius-2000 - 28_10...)
    match_sirius = re.match(r'^Sirius(?:Lora)?[\s_-]*(\d+)(?:[\s_-]|\b|$)', filename, re.IGNORECASE)
    if match_sirius:
        return match_sirius.group(1)

    return ""


def _resolve_token(nome_arquivo: str, source_type: str, comm_type: str = None, serial: str = None) -> str:
    """
    Centraliza a regra de criação do Token para Andrômeda, Telix, Sirius (Datalogger) e DLQ.
    """
    base_name = os.path.splitext(nome_arquivo)[0]
    if base_name.upper().endswith("_FALHAS"):
        base_name = base_name[:-7]

    if source_type == "andromeda":
        return base_name

    # Para 'telix', 'sirius' ou 'dlq'
    serial_clean = (serial or "").strip()

    # Se for DLQ de um arquivo Andrômeda (ex: SiriusLora340_FALHAS.csv) e o campo série estiver vazio
    if source_type == "dlq" and not serial_clean and base_name.lower().startswith("siriuslora"):
        return base_name

    if not serial_clean:
        raise ValueError("O Nº de Série é obrigatório para processar este arquivo.")

    # Se o operador digitou o token inteiro manualmente no campo Série, respeita sem duplicar prefixo
    if serial_clean.lower().startswith("sirius") or (serial_clean.startswith("00") and len(serial_clean) > 4):
        return serial_clean

    if comm_type == COMM_WIFI:
        return f"{PREFIX_WIFI}{serial_clean}"
    elif comm_type == COMM_NBIOT:
        return f"{PREFIX_NBIOT}{serial_clean}"
    elif comm_type == COMM_LORA:
        return f"{PREFIX_LORA}{serial_clean}"
    else:
        raise ValueError("Tipo de comunicação inválido (selecione WiFi, NB-IoT ou LoRa).")


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
                payload = json.loads(raw_json.replace('|', ','))

            if isinstance(payload, dict) and 'ts' in payload and 'values' in payload:
                payloads.append(payload)

            if max_rows and len(payloads) >= max_rows:
                break

    return payloads


def process_data(file_path: str, source_type: str, comm_type: str = None, serial: str = None):
    """
    Roteia o processamento com base na origem ('andromeda', 'telix', 'sirius' ou 'dlq').
    Aplica o filtro de qualidade ANTES de salvar o CSV convertido para que a planilha
    gerada reflita exatamente os dados limpos enviados ao Telix.
    Retorna: (payloads, token, discarded_count, discarded_filename)
    """
    try:
        nome_arquivo = os.path.basename(file_path)
        token = _resolve_token(nome_arquivo, source_type, comm_type, serial)

        # 1. Rota de Reprocessamento de Falhas (DLQ)
        if source_type == "dlq":
            payloads = _extract_dlq_payloads(file_path)
            log.info(f"Origem DLQ (Reprocessamento). {len(payloads)} pacotes recuperados para o token: {token}")
            return payloads, token, 0, None

        # 2. Rota Concentrador Andrômeda
        elif source_type == "andromeda":
            df = pd.read_csv(file_path, sep=',', encoding='utf-8')
            df = _convert_dates_to_ts(df)
            log.info(f"Origem Andrômeda. Token extraído: {token}")

        # 3. Rota Datalogger Sirius (Memória Interna)
        elif source_type == "sirius":
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0, index_col=False)
            df = _apply_sirius_etl_rules(df_raw, nome_arquivo)

        # 4. Rota Plataforma Telix
        else:
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0, index_col=False)
            df = _apply_telix_etl_rules(df_raw, nome_arquivo)

        # Aplica o filtro de qualidade e limpa o DataFrame (df_clean) ANTES de salvar o CSV convertido
        payloads, discarded_records, df_clean = _validate_and_build_payloads(df)

        if source_type in ("sirius", "telix"):
            output_dir = os.path.dirname(file_path)
            output_filename = f"convertido_{token}_{nome_arquivo}"

            df_para_salvar = df_clean.drop(columns=['ts'], errors='ignore')
            df_para_salvar.to_csv(os.path.join(output_dir, output_filename), index=False, sep=',', encoding='utf-8')
            log.info(f"Origem {source_type.capitalize()}. ETL e Filtro aplicados; arquivo convertido limpo salvo. Token: {token}")

        disc_filename = None
        if discarded_records:
            disc_path = _save_discarded_records(file_path, token, discarded_records)
            disc_filename = os.path.basename(disc_path)
            log.warning(
                f"[{token}] Filtro de Qualidade: {len(discarded_records)} leitura(s) de canais "
                f"descartada(s). Auditoria salva em: {disc_filename}"
            )

        return payloads, token, len(discarded_records), disc_filename

    except Exception as e:
        log.error(f"Erro no ETL ({os.path.basename(file_path)}): {str(e)}")
        raise e


def preview_data(file_path: str, source_type: str, comm_type: str = None, serial: str = None):
    """
    Executa um Dry-Run para visualização dos 3 primeiros Payloads válidos na interface (sem salvar arquivos).
    """
    try:
        nome_arquivo = os.path.basename(file_path)

        if source_type == "dlq":
            return _extract_dlq_payloads(file_path, max_rows=3)
        elif source_type == "andromeda":
            df = pd.read_csv(file_path, sep=',', encoding='utf-8', nrows=500)
            df = _convert_dates_to_ts(df)
        elif source_type == "sirius":
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0, nrows=500, index_col=False)
            df = _apply_sirius_etl_rules(df_raw, nome_arquivo)
        else:
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0, nrows=500, index_col=False)
            df = _apply_telix_etl_rules(df_raw, nome_arquivo)

        payloads, _, _ = _validate_and_build_payloads(df)
        return payloads[:3]

    except Exception as e:
        log.error(f"Erro ao gerar preview de {os.path.basename(file_path)}: {str(e)}")
        raise e


def _apply_telix_etl_rules(df: pd.DataFrame, nome_arquivo: str) -> pd.DataFrame:
    """
    Aplica a lógica de ETL em arquivos baixados do Telix (TimeStamp; Data Local; s1d1...),
    gerando o DataFrame no padrão exato do Andrômeda.
    """
    if df.shape[1] < 13:
        raise ValueError(f"Arquivo Telix {nome_arquivo} possui {df.shape[1]} colunas (esperado 13+). Dados incompletos.")

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


def _apply_sirius_etl_rules(df: pd.DataFrame, nome_arquivo: str) -> pd.DataFrame:
    """
    Aplica a lógica de ETL em arquivos brutos do datalogger Sirius:
    Cabeçalho original: n;ID;Datetime;Battery [V];Low Bat;Sens1 Data1;Sens1 Data2;...;Sens4 Data2
    Converte para o formato exato de 14 colunas do Andrômeda.
    """
    if df.shape[1] < 13:
        raise ValueError(f"Arquivo Sirius {nome_arquivo} possui {df.shape[1]} colunas (esperado 13+). Dados incompletos.")

    df_saida = pd.DataFrame()
    datas_limpas = df.iloc[:, 2].fillna('').astype(str).str.replace(',', '').str.strip()

    def formatar_data_sirius(val):
        # Suporta tanto ano com 2 dígitos (%y -> ex: 08/01/26) quanto 4 dígitos (%Y)
        for fmt in ('%d/%m/%y %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%d/%m/%y %H:%M', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(val, fmt).strftime('%d/%m/%Y %H:%M:%S')
            except ValueError:
                pass
        return val

    df_saida['Data/Hora'] = datas_limpas.apply(formatar_data_sirius)

    # No arquivo Sirius, os sensores começam na coluna 5 (Sens1 Data1) e vão até a 12 (Sens4 Data2)
    nomes_sensores = ['s1d1', 's1d2', 's2d1', 's2d2', 's3d1', 's3d2', 's4d1', 's4d2']
    for i, nome in enumerate(nomes_sensores):
        df_saida[nome] = df.iloc[:, i + 5].fillna('').astype(str).str.replace(',', '.').str.strip().replace('nan', '')

    # Battery [V] está na coluna 3 e Low Bat (0 ou 1) está na coluna 4
    baterias_raw = df.iloc[:, 3].fillna('').astype(str).str.replace(',', '.').str.strip()
    baterias_num = pd.to_numeric(baterias_raw, errors='coerce')
    lbat_raw = df.iloc[:, 4].fillna('').astype(str).str.strip().str.lower()

    df_saida['Bateria (V)'] = baterias_num.apply(lambda x: f"{x:.3f}" if pd.notna(x) else '')

    def definir_bat_fraca_sirius(idx):
        val_lbat = lbat_raw.iloc[idx]
        if val_lbat in ('1', 'true'):
            return 'True'
        if val_lbat in ('0', 'false'):
            return 'False'
        val_vbat = baterias_num.iloc[idx]
        if pd.notna(val_vbat):
            return 'True' if val_vbat < 3.1 else 'False'
        return ''

    df_saida['Bat Fraca'] = [definir_bat_fraca_sirius(i) for i in range(len(df))]

    # Datalogger interno não possui RSSI e SNR; colunas ficam vazias para igualar ao Andrômeda
    df_saida['RSSI'] = ''
    df_saida['SNR'] = ''
    df_saida['Inserido'] = df_saida['Data/Hora']

    df_saida = _convert_dates_to_ts(df_saida)
    return df_saida


def _map_channel_profiles(df: pd.DataFrame) -> dict:
    """
    Analisa o DataFrame completo para identificar quais canais estão em uso (possuem
    dados em sXd1) e quais canais utilizam o segundo dado (possuem dados válidos e >= 0 em sXd2).
    """
    profiles = {}
    for ch in range(1, 5):
        col_d1 = f"s{ch}d1"
        col_d2 = f"s{ch}d2"

        has_d1 = False
        has_d2 = False

        if col_d1 in df.columns:
            s_d1 = pd.to_numeric(
                df[col_d1].astype(str).str.replace(',', '.').str.strip(),
                errors='coerce'
            )
            has_d1 = bool(s_d1.notna().any())

        if col_d2 in df.columns:
            s_d2 = pd.to_numeric(
                df[col_d2].astype(str).str.replace(',', '.').str.strip(),
                errors='coerce'
            )
            # Considera que o canal possui 2º dado ativo se houver pelo menos uma leitura válida e não-negativa
            has_d2 = bool((s_d2.notna() & (s_d2 >= 0)).any())

        profiles[ch] = {
            "active": has_d1 or has_d2,
            "has_d1": has_d1,
            "has_d2": has_d2
        }

    return profiles


def _save_discarded_records(original_filepath: str, token: str, discarded_records: list) -> str:
    """
    Salva um relatório CSV de auditoria contendo todas as leituras de canais descartadas
    pelas regras de qualidade (dado primário vazio, dado secundário negativo ou ausente).
    """
    output_dir = os.path.dirname(original_filepath)
    base_name = os.path.splitext(os.path.basename(original_filepath))[0]

    prefix = f"convertido_{token}_"
    if base_name.lower().startswith(prefix.lower()):
        clean_base = base_name
    else:
        clean_base = f"convertido_{token}_{base_name}"

    out_filename = f"{clean_base}_DESCARTADOS.csv"
    out_path = os.path.join(output_dir, out_filename)

    df_disc = pd.DataFrame(discarded_records)
    df_disc.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
    return out_path


def _validate_and_build_payloads(df: pd.DataFrame) -> tuple:
    """
    Monta a lista de pacotes JSON aplicando o filtro inteligente por canal e também
    limpa os canais descartados diretamente em uma cópia do DataFrame (df_clean).
    Retorna: (valid_payloads, discarded_records, df_clean)
    """
    if df.empty:
        return [], [], df.copy()

    df_clean = df.copy()
    valid_payloads = []
    discarded_records = []
    channel_profiles = _map_channel_profiles(df_clean)

    def to_float(val):
        try:
            if pd.isna(val):
                return None
            s = str(val).strip().replace(',', '.')
            if s == '' or s.lower() == 'nan':
                return None
            return float(s)
        except Exception:
            return None

    for idx, row in df_clean.iterrows():
        if 'ts' not in row or pd.isna(row['ts']):
            continue

        ts_val = int(row['ts'])
        data_hora_str = str(row.get('Data/Hora', ''))
        values = {}

        for ch in range(1, 5):
            prof = channel_profiles[ch]
            if not prof["active"]:
                continue

            col_d1 = f"s{ch}d1"
            col_d2 = f"s{ch}d2"

            raw_d1 = row.get(col_d1, '')
            raw_d2 = row.get(col_d2, '')

            val_d1 = to_float(raw_d1)
            val_d2 = to_float(raw_d2)

            motivo_descarte = None

            # Regra 1: Primeiro dado (sXd1) vazio
            if val_d1 is None:
                motivo_descarte = f"Dado primario ({col_d1}) vazio ou invalido"

            # Regra 2: Segundo dado (sXd2) negativo (ex: temperatura negativa)
            elif val_d2 is not None and val_d2 < 0:
                motivo_descarte = f"Segundo dado ({col_d2}) negativo ({val_d2})"

            # Regra 3: Segundo dado (sXd2) vazio em canal que exige segundo dado
            elif prof["has_d2"] and val_d2 is None:
                motivo_descarte = f"Segundo dado ({col_d2}) vazio em canal duplo"

            if motivo_descarte:
                discarded_records.append({
                    "Data/Hora": data_hora_str,
                    "Timestamp (ms)": ts_val,
                    "Canal": f"Canal {ch}",
                    "Colunas Afetadas": f"{col_d1} / {col_d2}",
                    "Valor Primario (d1)": '' if pd.isna(raw_d1) else str(raw_d1).strip(),
                    "Valor Secundario (d2)": '' if pd.isna(raw_d2) else str(raw_d2).strip(),
                    "Motivo do Descarte": motivo_descarte
                })
                # Apaga os valores espúrios diretamente no DataFrame que será salvo no CSV convertido!
                if col_d1 in df_clean.columns:
                    df_clean.at[idx, col_d1] = ''
                if col_d2 in df_clean.columns:
                    df_clean.at[idx, col_d2] = ''
                continue

            values[col_d1] = val_d1
            if val_d2 is not None:
                values[col_d2] = val_d2

        vbat = to_float(row.get('Bateria (V)'))
        if vbat is not None:
            values['vbat'] = vbat

        lbat_str = str(row.get('Bat Fraca', '')).strip().lower()
        if lbat_str == 'true':
            values['lbat'] = True
        elif lbat_str == 'false':
            values['lbat'] = False

        rssi = to_float(row.get('RSSI'))
        if rssi is not None:
            values['rssi'] = rssi

        snr = to_float(row.get('SNR'))
        if snr is not None:
            values['snr'] = snr

        if values:
            valid_payloads.append({
                "ts": ts_val,
                "values": values
            })

    return valid_payloads, discarded_records, df_clean