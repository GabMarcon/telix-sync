import os
import pandas as pd
from datetime import datetime
from src.config import COMM_WIFI, COMM_NBIOT, PREFIX_WIFI, PREFIX_NBIOT
from src.core.logger import get_logger

log = get_logger()


def process_data(file_path, source_type, comm_type=None, serial=None):
    """
    Roteia o processamento com base na origem.
    Retorna a lista de payloads estruturada e o Token de acesso gerado.
    """
    try:
        nome_arquivo = os.path.basename(file_path)

        if source_type == "andromeda":
            token = os.path.splitext(nome_arquivo)[0]
            df = pd.read_csv(file_path, sep=',', encoding='utf-8')

            if 'Data/Hora' in df.columns:
                # CORREÇÃO DEFINITIVA: Localiza a data no fuso do Brasil antes de converter para Epoch
                df['ts'] = pd.to_datetime(df['Data/Hora'], format='%d/%m/%Y %H:%M:%S', errors='coerce').dt.tz_localize('America/Sao_Paulo').astype('int64') // 10 ** 6

            log.info(f"Origem Andrômeda. Token extraído: {token}")
        else:
            if comm_type == COMM_WIFI:
                token = f"{PREFIX_WIFI}{serial}"
            elif comm_type == COMM_NBIOT:
                token = f"{PREFIX_NBIOT}{serial}"
            else:
                raise ValueError("Tipo de comunicação inválido.")

            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0)
            df = _apply_etl_rules(df_raw, nome_arquivo)

            output_dir = os.path.dirname(file_path)
            output_filename = f"convertido_{token}_{nome_arquivo}"
            df.to_csv(os.path.join(output_dir, output_filename), index=False, sep=',', encoding='utf-8')
            log.info(f"Origem Telix. ETL aplicado. Token gerado: {token}")

        return _validate_and_build_payloads(df), token

    except Exception as e:
        log.error(f"Erro no ETL: {str(e)}")
        raise e


def preview_data(file_path, source_type, comm_type=None, serial=None):
    """
    Executa um Dry-Run nas 3 primeiras linhas para visualização do Payload na interface (sem salvar arquivos).
    """
    try:
        nome_arquivo = os.path.basename(file_path)

        if source_type == "andromeda":
            df = pd.read_csv(file_path, sep=',', encoding='utf-8', nrows=3)

            if 'Data/Hora' in df.columns:
                # Aplica a mesma lógica de fuso no preview
                df['ts'] = pd.to_datetime(df['Data/Hora'], format='%d/%m/%Y %H:%M:%S', errors='coerce').dt.tz_localize('America/Sao_Paulo').astype('int64') // 10 ** 6
        else:
            df_raw = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', dtype=str, header=0, nrows=3)
            df = _apply_etl_rules(df_raw, nome_arquivo)

        return _validate_and_build_payloads(df)

    except Exception as e:
        log.error(f"Erro ao gerar preview de {os.path.basename(file_path)}: {str(e)}")
        raise e


def _apply_etl_rules(df, nome_arquivo):
    """
    Aplica a lógica de ETL, gerando o DataFrame com as colunas formatadas
    para o arquivo CSV final.
    """
    if df.shape[1] < 13:
        raise ValueError(f"Arquivo {nome_arquivo} possui {df.shape[1]} colunas (esperado 13+). Dados incompletos.")

    df_saida = pd.DataFrame()
    datas_limpas = df.iloc[:, 1].astype(str).str.replace(',', '').str.strip()

    def formatar_data(val):
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(val, fmt).strftime('%d/%m/%Y %H:%M:%S')
            except ValueError:
                pass
        return val

    df_saida['Data/Hora'] = datas_limpas.apply(formatar_data)

    # CORREÇÃO DEFINITIVA: Informa que a data é do Brasil para gerar o Epoch exato
    df_saida['ts'] = pd.to_datetime(df_saida['Data/Hora'], format='%d/%m/%Y %H:%M:%S', errors='coerce').dt.tz_localize('America/Sao_Paulo').astype('int64') // 10 ** 6

    nomes_sensores = ['s1d1', 's1d2', 's2d1', 's2d2', 's3d1', 's3d2', 's4d1', 's4d2']
    for i, nome in enumerate(nomes_sensores):
        df_saida[nome] = df.iloc[:, i + 2].astype(str).str.replace(',', '.').replace('nan', '')

    baterias_raw = df.iloc[:, 11].astype(str).str.replace(',', '.')
    baterias_num = pd.to_numeric(baterias_raw, errors='coerce').fillna(0.0)

    df_saida['Bateria (V)'] = baterias_num.apply(lambda x: f"{x:.3f}")
    df_saida['Bat Fraca'] = baterias_num.apply(lambda x: 'True' if x < 3.1 else 'False')

    rssi_raw = df.iloc[:, 12].astype(str).str.strip().replace('nan', '')
    df_saida['RSSI'] = rssi_raw
    df_saida['SNR'] = ''
    df_saida['Inserido'] = df_saida['Data/Hora']

    return df_saida


def _validate_and_build_payloads(df):
    """
    Monta o JSON garantindo que as chaves da API (timeseries)
    sejam exatamente as exigidas pela cadeia histórica do Telix.
    """
    valid_payloads = []

    def to_float(val):
        try:
            if pd.isna(val) or str(val).strip() == '':
                return None
            return float(val)
        except:
            return None

    for _, row in df.iterrows():
        row_dict = row.to_dict()

        if 'ts' not in row_dict or pd.isna(row_dict['ts']):
            continue

        ts_val = int(row_dict['ts'])
        values = {}

        for s in ['s1d1', 's1d2', 's2d1', 's2d2', 's3d1', 's3d2', 's4d1', 's4d2']:
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