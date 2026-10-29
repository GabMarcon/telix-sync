import os
import json
import time
import asyncio
import aiohttp
from datetime import datetime
from src.config import CHECKPOINT_FILE
from src.core.logger import get_logger

log = get_logger()


# ==========================================
# FUNÇÕES AUXILIARES INTERNAS
# ==========================================
def _get_checkpoint(filepath: str) -> int:
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get(os.path.abspath(filepath), 0)
    except Exception:
        return 0


def _manage_checkpoint(filepath: str, last_idx: int = None, clear: bool = False):
    checkpoints = {}
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                checkpoints = json.load(f)
        except Exception:
            pass

    abs_path = os.path.abspath(filepath)
    if clear:
        checkpoints.pop(abs_path, None)
    elif last_idx is not None:
        checkpoints[abs_path] = last_idx

    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoints, f)


def _write_to_dlq(original_filepath: str, payload: dict, error_msg: str):
    base_name = os.path.splitext(os.path.basename(original_filepath))[0]
    if base_name.upper().endswith("_FALHAS"):
        base_name = base_name[:-7]

    dlq_file = os.path.join(os.path.dirname(original_filepath), f"{base_name}_FALHAS.csv")
    exists = os.path.exists(dlq_file)

    with open(dlq_file, 'a', encoding='utf-8') as f:
        if not exists:
            f.write("PAYLOAD_JSON;MOTIVO_ERRO\n")
        payload_str = json.dumps(payload, ensure_ascii=False)
        f.write(f"{payload_str};{error_msg}\n")


def _generate_report(file_path: str, processed: int, success: int, errors: int, start_time: float, host: str) -> str:
    server_id = host.replace("https://", "").replace("http://", "").split(".")[0].split(":")[0]
    data_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    prefix = "erros" if errors > 0 else "relatorio"
    report_name = f"{prefix}_{server_id}_{data_str}.txt"

    os.makedirs("logs", exist_ok=True)
    report_path = os.path.join("logs", report_name)

    elapsed = int(time.time() - start_time)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("=" * 40 + "\nRELATÓRIO DE REINSERÇÃO TELIX\n" + "=" * 40 + "\n\n")
        f.write(f"Arquivo Original: {os.path.basename(file_path)}\n")
        f.write(f"Servidor Alvo: {host}\n")
        f.write(f"Data de Conclusão: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"Tempo Total: {elapsed} segundos\n")
        f.write(f"Registros Processados: {processed}\n")
        f.write(f"Sucessos (Telix OK): {success}\n")
        f.write(f"Falhas (DLQ): {errors}\n")
    return report_path


def _format_eta(seconds: float) -> str:
    """Formata segundos restantes para um formato legível (ex: ~2m 15s)."""
    if seconds is None or seconds < 0 or seconds > 86400:
        return "Calculando..."
    secs = int(seconds)
    if secs < 60:
        return f"~{secs}s"
    mins = secs // 60
    rem_secs = secs % 60
    if mins < 60:
        return f"~{mins}m {rem_secs}s"
    hours = mins // 60
    rem_mins = mins % 60
    return f"~{hours}h {rem_mins}m"


# ==========================================
# MOTOR PRINCIPAL INTELIGENTE (ADAPTATIVE EPS)
# ==========================================
async def inject_telemetry_async(payloads, token, host, file_path, cancel_token=None, progress_callback=None,
                                 log_callback=None):
    total_payloads = len(payloads)
    if total_payloads == 0:
        raise ValueError("Nenhum pacote de telemetria válido encontrado no arquivo após o ETL.")

    url = f"{host.strip().rstrip('/')}/api/v1/{token}/telemetry"
    start_index = _get_checkpoint(file_path)

    if start_index >= total_payloads:
        if log_callback:
            log_callback("ℹ️ Arquivo já consta como 100% processado no Checkpoint. Ignorando injeção.")
        return

    # 1. Ajuste da Marcha Inicial
    if total_payloads < 1500:
        current_eps = 20.0
    elif total_payloads < 5000:
        current_eps = 15.0
    else:
        current_eps = 8.0

    if start_index > 0 and log_callback:
        log_callback(f"🔄 Retomando do Checkpoint: linha {start_index + 1} de {total_payloads}.")

    if log_callback:
        log_callback(f"[{token}] Carga de {total_payloads} pacotes. EPS Inicial: {current_eps} req/seg.")

    sucessos = 0
    erros = 0
    consecutive_success = 0
    start_time = time.time()

    MAX_EPS = 25.0
    MIN_EPS = 2.0
    timeout = aiohttp.ClientTimeout(total=30)
    token_error_message = None

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for current_idx in range(start_index, total_payloads):

            if cancel_token and cancel_token.cancelled:
                _manage_checkpoint(file_path, current_idx)
                if log_callback:
                    log_callback(f"⚠️ Injeção pausada pelo usuário. Checkpoint salvo na posição {current_idx}.")
                break

            cycle_start = time.time()
            payload = payloads[current_idx]

            retries = 3
            abort_file = False
            for attempt in range(retries):
                try:
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            sucessos += 1
                            consecutive_success += 1

                            if consecutive_success >= 150 and current_eps < MAX_EPS:
                                current_eps = min(MAX_EPS, current_eps + 2.0)
                                consecutive_success = 0
                                if log_callback:
                                    log_callback(f"Servidor estável. Acelerando para {current_eps} EPS.")

                            break

                        # Token recusado pelo ThingsBoard (401 Unauthorized / 404 Not Found)
                        elif response.status in [401, 404]:
                            token_error_message = (
                                f"Token '{token}' recusado pelo servidor (HTTP {response.status}). "
                                f"Verifique se a Rede (WiFi/NB-IoT/LoRa) ou Nº de Série estão corretos."
                            )
                            abort_file = True
                            break

                        elif response.status in [429, 500, 502, 503, 504]:
                            current_eps = max(MIN_EPS, current_eps * 0.5)
                            consecutive_success = 0

                            if log_callback and attempt == 0:
                                log_callback(
                                    f"⚠️ Rule Chain congestionada (HTTP {response.status}). Reduzindo para {current_eps} EPS."
                                )

                            if attempt < retries - 1:
                                await asyncio.sleep(5.0)
                            else:
                                _write_to_dlq(file_path, payload, f"HTTP_{response.status}")
                                erros += 1

                        else:
                            _write_to_dlq(file_path, payload, f"HTTP_{response.status}")
                            erros += 1
                            break

                except Exception:
                    current_eps = max(MIN_EPS, current_eps * 0.5)
                    consecutive_success = 0

                    if log_callback and attempt == 0:
                        log_callback(f"⚠️ Falha na rede/Timeout. Reduzindo para {current_eps} EPS.")

                    if attempt == retries - 1:
                        _write_to_dlq(file_path, payload, "TIMEOUT_OU_REDE")
                        erros += 1
                    else:
                        await asyncio.sleep(5.0)

            if abort_file:
                break

            # Atualiza barra de progresso e ETA a cada 10 envios ou no último pacote
            if progress_callback and ((current_idx + 1) % 10 == 0 or (current_idx + 1) == total_payloads):
                processed_count = (current_idx + 1) - start_index
                elapsed_total = time.time() - start_time
                if processed_count > 0 and elapsed_total > 0:
                    avg_speed = processed_count / elapsed_total
                    remaining_items = total_payloads - (current_idx + 1)
                    eta_seconds = remaining_items / avg_speed if avg_speed > 0 else 0
                    eta_str = _format_eta(eta_seconds)
                else:
                    eta_str = "Calculando..."
                progress_callback((current_idx + 1), total_payloads, current_eps, eta_str)

            if (current_idx + 1) % 1000 == 0:
                _manage_checkpoint(file_path, current_idx + 1)

            elapsed = time.time() - cycle_start
            min_cycle_time = 1.0 / current_eps
            if elapsed < min_cycle_time:
                await asyncio.sleep(min_cycle_time - elapsed)

    # Se abortou por Token inválido, não apaga eventual checkpoint anterior e dispara erro para a UI ficar vermelha
    if token_error_message:
        raise ValueError(token_error_message)

    # Se concluiu todos os pacotes sem ser cancelado, limpa o checkpoint e gera o relatório final
    if not (cancel_token and cancel_token.cancelled):
        _manage_checkpoint(file_path, clear=True)
        report_path = _generate_report(file_path, (sucessos + erros), sucessos, erros, start_time, host)
        if log_callback:
            log_callback(f"Injeção finalizada! Relatório salvo em: {report_path}")