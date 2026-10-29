import os
import json
import asyncio
import aiohttp
import flet as ft
from datetime import datetime
from src.config import COMM_WIFI, COMM_NBIOT, COMM_LORA
from src.core.etl_processor import process_data, preview_data, guess_serial_from_filename
from src.core.tb_injector import inject_telemetry_async
from src.core.logger import get_logger

# Definição global da versão do software
APP_VERSION = "1.3.0"

log = get_logger()


class CancelToken:
    def __init__(self):
        self.cancelled = False


def count_file_lines(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def detect_file_source(filepath):
    """
    Identifica automaticamente a origem do ficheiro pelo nome ou pela estrutura do cabeçalho:
    - 'dlq': Ficheiros terminados em _FALHAS.csv ou iniciados por PAYLOAD_JSON
    - 'sirius': Ficheiros extraídos diretamente do datalogger Sirius (cabeçalho contém Datetime / Sens1 Data1)
    - 'telix': Ficheiros exportados da plataforma Telix (separados por ';' com TimeStamp; Data Local)
    - 'andromeda': Ficheiros brutos do concentrador Andrômeda (separados por ',')
    """
    filename = os.path.basename(filepath).upper()
    if filename.endswith("_FALHAS.CSV"):
        return "dlq"
    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='ignore') as f:
            header = f.readline()
            header_upper = header.upper()
            if header_upper.startswith("PAYLOAD_JSON"):
                return "dlq"
            if ';' in header:
                if "DATETIME" in header_upper or "SENS1 DATA1" in header_upper or "BATTERY [V]" in header_upper:
                    return "sirius"
                return "telix"
            return "andromeda"
    except Exception:
        return "andromeda"


class FileConfigRow(ft.Container):
    def __init__(self, filepath, lines_count, detected_source, initial_serial, row_index, page: ft.Page, on_delete, on_change_callback=None):
        super().__init__()
        self.page = page
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.lines_count = lines_count
        self.on_delete_callback = on_delete
        self.on_change_callback = on_change_callback
        self.current_status = "pending"

        # Estilo Zebra (alternância sutil entre linhas pares e ímpares)
        self.bgcolor = "#1b2026" if row_index % 2 == 0 else "#15191e"
        self.padding = ft.padding.symmetric(vertical=6, horizontal=12)
        self.border = ft.border.only(bottom=ft.border.BorderSide(1, ft.colors.OUTLINE_VARIANT))

        self.lbl_name = ft.Text(
            self.filename,
            tooltip=self.filepath,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            weight=ft.FontWeight.W_500
        )
        self.lbl_lines = ft.Text(f"{self.lines_count:,}".replace(",", "."), text_align=ft.TextAlign.CENTER)

        self.dd_source = ft.Dropdown(
            options=[
                ft.dropdown.Option("andromeda", "Andrômeda"),
                ft.dropdown.Option("telix", "Telix"),
                ft.dropdown.Option("sirius", "Sirius"),
                ft.dropdown.Option("dlq", "Falhas (DLQ)")
            ],
            value=detected_source,
            on_change=self.on_source_change,
            text_size=13,
            height=38,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=5)
        )

        needs_config = detected_source in ("telix", "sirius", "dlq")

        self.dd_comm = ft.Dropdown(
            options=[
                ft.dropdown.Option(COMM_WIFI),
                ft.dropdown.Option(COMM_NBIOT),
                ft.dropdown.Option(COMM_LORA)
            ],
            value=COMM_WIFI,
            disabled=not needs_config,
            text_size=13,
            height=38,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=5)
        )

        self.txt_serial = ft.TextField(
            value=initial_serial,
            hint_text="Obrigatório" if needs_config else "Automático",
            disabled=not needs_config,
            on_change=self.on_serial_change,
            text_size=13,
            height=38,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=5)
        )

        self.btn_preview = ft.IconButton(
            icon=ft.icons.MANAGE_SEARCH,
            icon_color=ft.colors.PRIMARY,
            tooltip="Pré-visualizar Payload (Dry Run)",
            on_click=self.show_preview
        )

        self.btn_delete = ft.IconButton(
            icon=ft.icons.DELETE_OUTLINE,
            icon_color=ft.colors.RED_400,
            tooltip="Remover Arquivo da Fila",
            on_click=self.delete_clicked
        )

        self.status_icon = ft.Icon(ft.icons.SCHEDULE, color=ft.colors.GREY_500, tooltip="Aguardando na fila")

        # Aplica validação visual inicial (borda âmbar se faltar Série em Telix/Sirius/DLQ)
        self._apply_serial_validation_style()

        self.content = ft.Row([
            ft.Container(content=self.lbl_name, expand=True, padding=ft.padding.only(right=10)),
            ft.Container(content=self.lbl_lines, width=85, alignment=ft.alignment.center),
            ft.Container(content=self.dd_source, width=140),
            ft.Container(content=self.dd_comm, width=115),
            ft.Container(content=self.txt_serial, width=135),
            ft.Container(content=self.btn_preview, width=45, alignment=ft.alignment.center),
            ft.Container(content=self.status_icon, width=60, alignment=ft.alignment.center),
            ft.Container(content=self.btn_delete, width=45, alignment=ft.alignment.center)
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _is_serial_required(self) -> bool:
        src = self.dd_source.value
        if src == "andromeda":
            return False
        base_check = os.path.splitext(self.filename)[0]
        if src == "dlq" and base_check.lower().startswith("siriuslora"):
            return False
        return True

    def _apply_serial_validation_style(self):
        needs_config = self.dd_source.value in ("telix", "sirius", "dlq")
        self.dd_comm.disabled = not needs_config
        self.txt_serial.disabled = not needs_config

        if self._is_serial_required() and not (self.txt_serial.value or "").strip():
            self.txt_serial.border_color = ft.colors.AMBER_400
            self.txt_serial.border_width = 2
            self.txt_serial.hint_text = "⚠️ Digite a Série"
        else:
            self.txt_serial.border_color = ft.colors.OUTLINE
            self.txt_serial.border_width = 1
            self.txt_serial.hint_text = "Série" if needs_config else "Automático"

    def on_source_change(self, e):
        self._apply_serial_validation_style()
        self.update()
        if self.on_change_callback:
            self.on_change_callback()

    def on_serial_change(self, e):
        self._apply_serial_validation_style()
        self.update()

    def set_comm_type(self, comm_value: str):
        if self.dd_source.value in ("telix", "sirius", "dlq"):
            self.dd_comm.value = comm_value
            self.update()

    def set_zebra_index(self, row_index: int):
        self.bgcolor = "#1b2026" if row_index % 2 == 0 else "#15191e"

    def get_config(self):
        return {
            "path": self.filepath,
            "source": self.dd_source.value,
            "comm": self.dd_comm.value,
            "serial": self.txt_serial.value.strip()
        }

    def delete_clicked(self, e):
        self.on_delete_callback(self)

    def show_preview(self, e):
        config = self.get_config()
        try:
            payloads = preview_data(config["path"], config["source"], config["comm"], config["serial"])
            payload_str = json.dumps(payloads, indent=4, ensure_ascii=False)
        except Exception as ex:
            payload_str = f"❌ Erro na extração:\n{str(ex)}"

        dlg = ft.AlertDialog(
            title=ft.Text("Amostra de Payload (Dry Run)", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Arquivo: {self.filename}", italic=True),
                    ft.Text("Visualizando apenas as 3 primeiras linhas como JSON puro:", color=ft.colors.GREY_400),
                    ft.TextField(
                        value=payload_str,
                        multiline=True,
                        read_only=True,
                        expand=True,
                        text_size=13,
                        text_style=ft.TextStyle(font_family="Consolas")
                    )
                ], expand=True),
                width=650,
                height=450
            ),
            actions=[ft.TextButton("Fechar", on_click=lambda e: self.close_dlg(dlg))]
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def close_dlg(self, dlg):
        dlg.open = False
        self.page.update()

    def set_status(self, status, tooltip=""):
        self.current_status = status
        if status == "processing":
            self.status_icon.name = ft.icons.SYNC
            self.status_icon.color = ft.colors.PRIMARY
            self.status_icon.tooltip = "Processando..."
            self.btn_delete.disabled = True
        elif status == "success":
            self.status_icon.name = ft.icons.CHECK_CIRCLE
            self.status_icon.color = ft.colors.GREEN_400
            self.status_icon.tooltip = "Concluído com sucesso"
            self.btn_delete.disabled = False
        elif status == "error":
            self.status_icon.name = ft.icons.ERROR
            self.status_icon.color = ft.colors.RED_400
            self.status_icon.tooltip = tooltip
            self.btn_delete.disabled = False
        elif status == "cancelled":
            self.status_icon.name = ft.icons.BLOCK
            self.status_icon.color = ft.colors.ORANGE_400
            self.status_icon.tooltip = "Cancelado pelo usuário"
            self.btn_delete.disabled = False
        self.update()


def main_gui(page: ft.Page):
    page.title = f"Telix Sync v{APP_VERSION}"
    page.theme_mode = ft.ThemeMode.DARK

    page.window_icon = "logo.png"
    page.window_width = 1160
    page.window_height = 940
    page.window_min_width = 1100
    page.window_min_height = 820
    page.padding = 16
    page.theme = ft.Theme(color_scheme_seed="#0cbda9")

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.icons.HUB, color="#0cbda9"),
        leading_width=45,
        title=ft.Row([
            ft.Text("Telix Sync", weight=ft.FontWeight.BOLD, size=20),
            ft.Container(
                content=ft.Text(f"v{APP_VERSION}", size=11, weight=ft.FontWeight.BOLD, color=ft.colors.BLACK),
                bgcolor="#0cbda9",
                padding=ft.padding.symmetric(horizontal=8, vertical=2),
                border_radius=10
            ),
            ft.Text(" |  Injetor de Telemetria em Massa", size=13, color=ft.colors.GREY_400)
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        center_title=False,
        bgcolor=ft.colors.SURFACE_VARIANT,
        elevation=2,
        actions=[
            ft.Container(
                content=ft.Image(src="auro.png", height=28, fit=ft.ImageFit.CONTAIN),
                padding=ft.padding.only(right=20)
            )
        ]
    )

    file_rows = []
    cancel_token = CancelToken()

    # ==========================================
    # SEÇÃO 2: INDICADORES DE PERFORMANCE (KPIs)
    # ==========================================
    lbl_kpi_files = ft.Text("0 / 0", size=20, weight=ft.FontWeight.BOLD)
    lbl_kpi_lines = ft.Text("0", size=20, weight=ft.FontWeight.BOLD)
    lbl_kpi_speed = ft.Text("0 req/s", size=20, weight=ft.FontWeight.BOLD, color="#0cbda9")
    lbl_kpi_eta = ft.Text("--", size=20, weight=ft.FontWeight.BOLD, color=ft.colors.AMBER_300)

    def build_kpi_card(title: str, value_control: ft.Text, icon_name: str, icon_color: str):
        return ft.Card(
            expand=True,
            elevation=1,
            content=ft.Container(
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(icon_name, color=icon_color, size=26),
                        bgcolor=ft.colors.SURFACE_VARIANT,
                        padding=10,
                        border_radius=10
                    ),
                    ft.Column([
                        ft.Text(title, size=12, color=ft.colors.GREY_400, weight=ft.FontWeight.W_500),
                        value_control
                    ], spacing=2)
                ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )
        )

    kpi_row = ft.Row([
        build_kpi_card("Arquivos Concluídos", lbl_kpi_files, ft.icons.FOLDER_COPY_OUTLINED, ft.colors.BLUE_300),
        build_kpi_card("Volume na Fila (Linhas)", lbl_kpi_lines, ft.icons.FORMAT_LIST_NUMBERED, ft.colors.PURPLE_300),
        build_kpi_card("Cadência Atual (EPS)", lbl_kpi_speed, ft.icons.SPEED, "#0cbda9"),
        build_kpi_card("Tempo Estimado (ETA)", lbl_kpi_eta, ft.icons.TIMER_OUTLINED, ft.colors.AMBER_300),
    ], spacing=12)

    def refresh_kpis(current_eps=None, eta_str=None):
        total_files = len(file_rows)
        done_files = sum(1 for r in file_rows if r.current_status == "success")
        total_lines = sum(r.lines_count for r in file_rows)

        lbl_kpi_files.value = f"{done_files} / {total_files}"
        lbl_kpi_lines.value = f"{total_lines:,}".replace(",", ".")

        if current_eps is not None:
            lbl_kpi_speed.value = f"{current_eps:.0f} req/s"
        if eta_str is not None:
            lbl_kpi_eta.value = eta_str

    # ==========================================
    # TERMINAL COLORIDO POR SEMÂNTICA
    # ==========================================
    log_view = ft.ListView(expand=True, spacing=3, auto_scroll=True)

    def add_log(msg: str):
        time_str = datetime.now().strftime('%H:%M:%S')
        msg_upper = msg.upper()

        if any(k in msg_upper for k in ("ERRO", "FALHA", "❌", "ABORTADO", "INACESSÍVEL", "RECUSADO")):
            text_color = ft.colors.RED_300
        elif any(k in msg_upper for k in ("⚠️", "AVISO", "CONGESTIONADA", "REDUZINDO", "ATENÇÃO", "CANCELADO", "PAUSADA")):
            text_color = ft.colors.AMBER_300
        elif any(k in msg_upper for k in ("OK:", "✅", "BEM-SUCEDIDO", "FINALIZADA", "ESTÁVEL", "CONCLUÍDA")):
            text_color = ft.colors.GREEN_300
        elif msg.startswith("---") or msg.startswith(">"):
            text_color = ft.colors.CYAN_200
        else:
            text_color = ft.colors.GREY_300

        if len(log_view.controls) >= 200:
            log_view.controls.pop(0)

        log_view.controls.append(
            ft.Text(f"[{time_str}] {msg}", size=12.5, font_family="Consolas", color=text_color)
        )
        log.info(msg)
        page.update()

    def clear_terminal(e):
        log_view.controls.clear()
        page.update()

    # ==========================================
    # GERENCIAMENTO DA FILA DE ARQUIVOS
    # ==========================================
    empty_state_container = ft.Container(
        padding=35,
        alignment=ft.alignment.center,
        content=ft.Column([
            ft.Icon(ft.icons.UPLOAD_FILE_OUTLINED, size=40, color=ft.colors.GREY_600),
            ft.Text("Nenhum arquivo na fila de processamento.", size=14, color=ft.colors.GREY_400, weight=ft.FontWeight.W_500),
            ft.Text("Clique em 'Adicionar Arquivos' para carregar planilhas do Andrômeda, Telix, Datalogger Sirius ou _FALHAS.csv.", size=12, color=ft.colors.GREY_600)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)
    )

    files_list_view = ft.ListView(spacing=0, expand=True, auto_scroll=False)

    def remove_file_from_list(row_to_remove):
        if row_to_remove in file_rows:
            file_rows.remove(row_to_remove)
        if row_to_remove in files_list_view.controls:
            files_list_view.controls.remove(row_to_remove)

        for idx, r in enumerate(file_rows):
            r.set_zebra_index(idx)

        empty_state_container.visible = len(files_list_view.controls) == 0
        refresh_kpis()
        page.update()

    def clear_queue(e):
        files_list_view.controls.clear()
        file_rows.clear()
        empty_state_container.visible = True
        refresh_kpis(current_eps=0, eta_str="--")
        page.update()

    def set_all_comm(comm_type: str):
        count = 0
        for r in file_rows:
            if r.dd_source.value in ("telix", "sirius", "dlq"):
                r.set_comm_type(comm_type)
                count += 1
        if count > 0:
            add_log(f"Rede alterada em lote para '{comm_type}' em {count} arquivo(s).")

    def on_files_picked(e: ft.FilePickerResultEvent):
        if e.files:
            existing_paths = [r.filepath for r in file_rows]
            auto_filled = 0
            manual_needed = 0

            for f in e.files:
                if f.path not in existing_paths:
                    linhas = count_file_lines(f.path)
                    origem_detectada = detect_file_source(f.path)
                    serie_sugerida = ""

                    if origem_detectada in ("telix", "sirius", "dlq"):
                        serie_sugerida = guess_serial_from_filename(f.path)
                        if serie_sugerida:
                            auto_filled += 1
                        else:
                            manual_needed += 1

                    row = FileConfigRow(
                        filepath=f.path,
                        lines_count=linhas,
                        detected_source=origem_detectada,
                        initial_serial=serie_sugerida,
                        row_index=len(file_rows),
                        page=page,
                        on_delete=remove_file_from_list,
                        on_change_callback=refresh_kpis
                    )
                    file_rows.append(row)
                    files_list_view.controls.append(row)

            empty_state_container.visible = len(files_list_view.controls) == 0
            refresh_kpis()

            if auto_filled > 0:
                add_log(f"ℹ️ {auto_filled} Nº(s) de série identificado(s) automaticamente pelo nome do arquivo.")
            if manual_needed > 0:
                add_log(f"⚠️ Atenção: {manual_needed} arquivo(s) sem série no nome (ex: default_ ou DL-XX). Preencha o campo 'Nº de Série' destacado em amarelo.")
            page.update()

    file_picker = ft.FilePicker(on_result=on_files_picked)
    page.overlay.append(file_picker)

    # ==========================================
    # SEÇÃO 1: BARRA SUPERIOR COMPACTA DE CONEXÃO
    # ==========================================
    saved_type = page.client_storage.get("server_type") or "cloud"
    saved_val = page.client_storage.get("server_val") or ""

    server_type_radio = ft.RadioGroup(
        value=saved_type,
        content=ft.Row([
            ft.Radio(value="cloud", label="Nuvem (Cliente)"),
            ft.Radio(value="local", label="Servidor IP")
        ], spacing=10)
    )

    server_input = ft.TextField(
        value=saved_val,
        width=330,
        height=40,
        text_size=13,
        content_padding=ft.padding.symmetric(horizontal=12, vertical=8)
    )
    lbl_conn_status = ft.Text("", size=12.5, weight=ft.FontWeight.BOLD)

    def apply_server_style():
        lbl_conn_status.value = ""
        if server_type_radio.value == "cloud":
            server_input.label = "Subdomínio do Cliente"
            server_input.prefix_text = "https://"
            server_input.suffix_text = ".telix.com.br"
            server_input.hint_text = "ex: minasgerais"
        else:
            server_input.label = "Endereço IP Local"
            server_input.prefix_text = "http://"
            server_input.suffix_text = ":8080"
            server_input.hint_text = "ex: 192.168.0.90"

    apply_server_style()

    def handle_server_type_change(e):
        apply_server_style()
        page.update()

    server_type_radio.on_change = handle_server_type_change

    async def test_server_connection(e):
        val = server_input.value.strip()
        if not val:
            lbl_conn_status.value = "⚠️ Informe o servidor"
            lbl_conn_status.color = ft.colors.AMBER_400
            page.update()
            return

        url = f"https://{val}.telix.com.br" if server_type_radio.value == "cloud" else f"http://{val}:8080"
        lbl_conn_status.value = "⏳ Testando..."
        lbl_conn_status.color = ft.colors.BLUE_300
        page.update()

        try:
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    lbl_conn_status.value = f"✅ Online (HTTP {resp.status})"
                    lbl_conn_status.color = ft.colors.GREEN_400
                    add_log(f"✅ Conexão verificada com sucesso em {url} (HTTP {resp.status}).")
        except Exception as ex:
            lbl_conn_status.value = "❌ Offline / Inacessível"
            lbl_conn_status.color = ft.colors.RED_400
            add_log(f"❌ Falha ao conectar em {url}: {str(ex)}")
        page.update()

    btn_test_conn = ft.OutlinedButton(
        "Testar Servidor",
        icon=ft.icons.WIFI_FIND,
        height=40,
        on_click=test_server_connection
    )

    card_server = ft.Card(
        elevation=1,
        content=ft.Container(
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.icons.DNS_OUTLINED, color=ft.colors.PRIMARY, size=20),
                    ft.Text("Servidor Alvo:", weight=ft.FontWeight.BOLD, size=14),
                ], spacing=8),
                server_type_radio,
                server_input,
                btn_test_conn,
                lbl_conn_status
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, wrap=True)
        )
    )

    # ==========================================
    # SEÇÃO 3: TABELA DA FILA DE ARQUIVOS
    # ==========================================
    table_header = ft.Container(
        bgcolor=ft.colors.SURFACE_VARIANT,
        padding=ft.padding.symmetric(vertical=10, horizontal=12),
        border_radius=ft.border_radius.only(top_left=8, top_right=8),
        content=ft.Row([
            ft.Container(content=ft.Text("Nome do Arquivo", weight=ft.FontWeight.BOLD, size=13), expand=True,
                         padding=ft.padding.only(right=10)),
            ft.Container(content=ft.Text("Registros", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER),
                         width=85, alignment=ft.alignment.center),
            ft.Container(content=ft.Text("Origem", weight=ft.FontWeight.BOLD, size=13), width=140),
            ft.Container(content=ft.Text("Rede", weight=ft.FontWeight.BOLD, size=13), width=115),
            ft.Container(content=ft.Text("Nº de Série", weight=ft.FontWeight.BOLD, size=13), width=135),
            ft.Container(content=ft.Text("JSON", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER),
                         width=45, alignment=ft.alignment.center),
            ft.Container(content=ft.Text("Status", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER),
                         width=60, alignment=ft.alignment.center),
            ft.Container(content=ft.Text("Ação", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER),
                         width=45, alignment=ft.alignment.center)
        ])
    )

    card_files = ft.Card(
        expand=3,
        elevation=1,
        content=ft.Container(
            padding=14,
            content=ft.Column([
                ft.Row([
                    ft.Row([
                        ft.Icon(ft.icons.PLAYLIST_ADD_CHECK, color=ft.colors.PRIMARY),
                        ft.Text("Fila de Processamento", style=ft.TextThemeStyle.TITLE_MEDIUM, weight=ft.FontWeight.BOLD),
                    ], spacing=8),
                    ft.Row([
                        ft.OutlinedButton("Todos WiFi", icon=ft.icons.WIFI, height=36,
                                          tooltip="Definir rede WiFi para todos os arquivos Telix/Sirius/DLQ",
                                          on_click=lambda _: set_all_comm(COMM_WIFI)),
                        ft.OutlinedButton("Todos NB-IoT", icon=ft.icons.CELL_TOWER, height=36,
                                          tooltip="Definir rede NB-IoT para todos os arquivos Telix/Sirius/DLQ",
                                          on_click=lambda _: set_all_comm(COMM_NBIOT)),
                        ft.OutlinedButton("Todos LoRa", icon=ft.icons.SETTINGS_INPUT_ANTENNA, height=36,
                                          tooltip="Definir rede LoRa (SiriusLora) para todos os arquivos Telix/Sirius/DLQ",
                                          on_click=lambda _: set_all_comm(COMM_LORA)),
                        ft.ElevatedButton("Limpar Fila", icon=ft.icons.DELETE_SWEEP, height=36, color=ft.colors.RED_300,
                                          on_click=clear_queue),
                        ft.FilledTonalButton("Adicionar Arquivos", icon=ft.icons.ADD_BOX, height=36,
                                             on_click=lambda _: file_picker.pick_files(allow_multiple=True,
                                                                                       allowed_extensions=["csv", "txt"]))
                    ], spacing=8)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Column([
                    table_header,
                    ft.Container(
                        expand=True,
                        content=ft.Column([empty_state_container, files_list_view], expand=True, spacing=0),
                        border=ft.border.all(1, ft.colors.OUTLINE_VARIANT),
                        border_radius=ft.border_radius.only(bottom_left=8, bottom_right=8),
                        padding=0
                    )
                ], spacing=0, expand=True)
            ], expand=True, spacing=10)
        )
    )

    # ==========================================
    # SEÇÃO 4: CONTROLES DE EXECUÇÃO E PROGRESSO
    # ==========================================
    progress_bar = ft.ProgressBar(value=0, visible=False, color=ft.colors.PRIMARY, bgcolor=ft.colors.GREY_800, bar_height=8)
    progress_text = ft.Text(value="", visible=False, size=12.5, weight=ft.FontWeight.W_500, color=ft.colors.GREY_300)

    btn_run = ft.FilledButton(
        "Iniciar Sincronização em Massa",
        icon=ft.icons.PLAY_ARROW,
        height=44,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
    )

    btn_cancel = ft.FilledButton(
        "Parada Segura (Salvar Checkpoint)",
        icon=ft.icons.STOP,
        height=44,
        disabled=True,
        style=ft.ButtonStyle(
            color=ft.colors.WHITE,
            bgcolor=ft.colors.RED_700,
            shape=ft.RoundedRectangleBorder(radius=8)
        )
    )

    def update_progress(current, total, eps=0.0, eta_str="Calculando..."):
        pct = (current / total * 100) if total > 0 else 0
        progress_bar.value = current / total if total > 0 else 0
        progress_text.value = f"Progresso do arquivo atual: {current:,} de {total:,} registros ({pct:.1f}%)".replace(",", ".")
        refresh_kpis(current_eps=eps, eta_str=eta_str)
        page.update()

    def on_cancel_click(e):
        cancel_token.cancelled = True
        btn_cancel.disabled = True
        add_log("⚠️ Sinal de parada enviado. Aguardando conclusão do pacote atual para salvar o checkpoint...")
        page.update()

    btn_cancel.on_click = on_cancel_click

    def close_success_dlg(e):
        page.dialog.open = False
        page.update()

    def open_logs_and_close(e):
        if os.path.exists("logs"):
            os.startfile("logs")
        close_success_dlg(e)

    success_dlg = ft.AlertDialog(
        title=ft.Text("Processamento Finalizado!", weight=ft.FontWeight.BOLD),
        content=ft.Text(
            "A fila de arquivos foi processada. Verifique o status na tabela e os relatórios na pasta /logs para detalhes."),
        actions=[
            ft.TextButton("Abrir Pasta de Relatórios", on_click=open_logs_and_close, icon=ft.icons.FOLDER_OPEN,
                          icon_color=ft.colors.PRIMARY),
            ft.TextButton("Fechar", on_click=close_success_dlg)
        ]
    )

    async def execute_pipeline(e):
        if not file_rows:
            add_log("ERRO: Adicione pelo menos um arquivo CSV à fila antes de iniciar.")
            return

        server_val = server_input.value.strip()
        if not server_val:
            add_log("ERRO: Preencha o subdomínio ou IP do Servidor Alvo no topo da tela.")
            return

        await page.client_storage.set_async("server_type", server_type_radio.value)
        await page.client_storage.set_async("server_val", server_val)

        if server_type_radio.value == "cloud":
            final_tb_url = f"https://{server_val}.telix.com.br"
        else:
            final_tb_url = f"http://{server_val}:8080"

        cancel_token.cancelled = False
        btn_run.disabled = True
        btn_cancel.disabled = False
        page.update()

        add_log(f"--- Iniciando Sincronização Telix Sync -> {final_tb_url} ---")

        for row in file_rows:
            if cancel_token.cancelled:
                add_log("⚠️ Lote interrompido pelo usuário. Os arquivos restantes permaneceram na fila.")
                break

            config = row.get_config()
            base_check = os.path.splitext(os.path.basename(config["path"]))[0]

            is_andromeda_dlq = config["source"] == "dlq" and base_check.lower().startswith("siriuslora")
            if config["source"] in ("telix", "sirius", "dlq") and not config["serial"] and not is_andromeda_dlq:
                add_log(f"⚠️ AVISO: Arquivo ignorado: {os.path.basename(config['path'])} (Nº de Série não preenchido)")
                row.set_status("error", "Série pendente")
                continue

            row.set_status("processing")
            add_log(f"> Processando arquivo: {os.path.basename(config['path'])} (Origem: {config['source'].upper()})")

            progress_bar.value = 0
            progress_bar.visible = True
            progress_text.value = "Executando ETL e preparando pacotes JSON..."
            progress_text.visible = True
            page.update()

            try:
                payloads, token = await asyncio.to_thread(
                    process_data,
                    config["path"],
                    config["source"],
                    config["comm"],
                    config["serial"]
                )

                await inject_telemetry_async(
                    payloads=payloads,
                    token=token,
                    host=final_tb_url,
                    file_path=config["path"],
                    cancel_token=cancel_token,
                    progress_callback=update_progress,
                    log_callback=add_log
                )

                if cancel_token.cancelled:
                    row.set_status("cancelled")
                else:
                    row.set_status("success")
                    add_log(f"OK: Arquivo {os.path.basename(config['path'])} sincronizado com sucesso.")

            except PermissionError:
                row.set_status("error", "Bloqueado (Excel/Windows)")
                add_log(
                    f"❌ ERRO: O arquivo {os.path.basename(config['path'])} está aberto no Excel ou outro programa. Feche-o e tente novamente.")
            except Exception as ex:
                row.set_status("error", str(ex))
                add_log(f"❌ ERRO em {os.path.basename(config['path'])}: {str(ex)}")

            refresh_kpis()

        btn_run.disabled = False
        btn_cancel.disabled = True
        progress_bar.visible = False
        progress_text.visible = False
        refresh_kpis(current_eps=0, eta_str="Concluído" if not cancel_token.cancelled else "Pausado")

        log_view.controls.append(
            ft.Row([
                ft.Text("--- Fim do Processamento ---", size=12.5, font_family="Consolas", color=ft.colors.CYAN_200),
                ft.TextButton("Abrir Pasta de Relatórios (/logs)", icon=ft.icons.FOLDER_OPEN, icon_color=ft.colors.PRIMARY,
                              on_click=lambda _: os.startfile("logs") if os.path.exists("logs") else None)
            ])
        )
        page.update()

        if not cancel_token.cancelled:
            page.dialog = success_dlg
            success_dlg.open = True
            page.update()

    btn_run.on_click = execute_pipeline

    # ==========================================
    # SEÇÃO 5: TERMINAL DE EXECUÇÃO
    # ==========================================
    terminal_container = ft.Container(
        expand=2,
        bgcolor="#111418",
        border=ft.border.all(1, ft.colors.OUTLINE_VARIANT),
        border_radius=10,
        padding=ft.padding.symmetric(horizontal=14, vertical=10),
        content=ft.Column([
            ft.Row([
                ft.Row([
                    ft.Icon(ft.icons.TERMINAL, size=18, color=ft.colors.GREY_400),
                    ft.Text("Terminal de Execução e Diagnóstico", weight=ft.FontWeight.BOLD, size=13, color=ft.colors.GREY_300),
                ], spacing=8),
                ft.Row([
                    ft.TextButton(
                        "Abrir Relatórios",
                        icon=ft.icons.FOLDER_OPEN,
                        style=ft.ButtonStyle(color=ft.colors.GREY_400),
                        on_click=lambda _: os.startfile("logs") if os.path.exists("logs") else None
                    ),
                    ft.IconButton(
                        icon=ft.icons.CLEANING_SERVICES_OUTLINED,
                        icon_size=18,
                        icon_color=ft.colors.GREY_400,
                        tooltip="Limpar Terminal",
                        on_click=clear_terminal
                    )
                ], spacing=4)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(height=1, color=ft.colors.OUTLINE_VARIANT),
            log_view
        ], expand=True, spacing=6)
    )

    # ==========================================
    # MONTAGEM DO LAYOUT PRINCIPAL
    # ==========================================
    main_layout = ft.Column(
        expand=True,
        spacing=10,
        controls=[
            card_server,
            kpi_row,
            card_files,
            ft.Container(
                content=ft.Column([
                    ft.Row([btn_run, btn_cancel], alignment=ft.MainAxisAlignment.CENTER, spacing=15),
                    progress_bar,
                    ft.Row([progress_text], alignment=ft.MainAxisAlignment.CENTER)
                ], spacing=6),
                padding=ft.padding.symmetric(vertical=2)
            ),
            terminal_container
        ]
    )

    page.add(main_layout)