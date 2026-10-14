import os
import json
import flet as ft
from datetime import datetime
from src.config import COMM_WIFI, COMM_NBIOT
from src.core.etl_processor import process_data, preview_data
from src.core.tb_injector import inject_telemetry_async
from src.core.logger import get_logger

# Definição global da versão do software
APP_VERSION = "1.0.0"

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
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            header = f.readline()
            if ';' in header:
                return "telix"
            return "andromeda"
    except Exception:
        return "andromeda"


class FileConfigRow(ft.Container):
    def __init__(self, filepath, lines_count, detected_source, page: ft.Page, on_delete):
        super().__init__()
        self.page = page
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.lines_count = lines_count
        self.on_delete_callback = on_delete
        self.padding = ft.padding.symmetric(vertical=5, horizontal=10)
        self.border = ft.border.only(bottom=ft.border.BorderSide(1, ft.colors.OUTLINE_VARIANT))

        self.lbl_name = ft.Text(self.filename, tooltip=self.filepath, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
        self.lbl_lines = ft.Text(f"{self.lines_count:,}".replace(",", "."), text_align=ft.TextAlign.CENTER)

        self.dd_source = ft.Dropdown(
            options=[ft.dropdown.Option("andromeda", "Andrômeda"), ft.dropdown.Option("telix", "Telix")],
            value=detected_source,
            on_change=self.on_source_change,
            text_size=13,
            height=40,
            content_padding=10
        )

        is_telix_initial = (detected_source == "telix")

        self.dd_comm = ft.Dropdown(
            options=[ft.dropdown.Option(COMM_WIFI), ft.dropdown.Option(COMM_NBIOT)],
            value=COMM_WIFI,
            disabled=not is_telix_initial,
            text_size=13,
            height=40,
            content_padding=10
        )

        self.txt_serial = ft.TextField(
            hint_text="Série",
            disabled=not is_telix_initial,
            text_size=13,
            height=40,
            content_padding=10
        )

        self.btn_preview = ft.IconButton(
            icon=ft.icons.MANAGE_SEARCH,
            icon_color=ft.colors.PRIMARY,
            tooltip="Pré-visualizar Payload",
            on_click=self.show_preview
        )

        self.btn_delete = ft.IconButton(
            icon=ft.icons.DELETE_OUTLINE,
            icon_color=ft.colors.RED_400,
            tooltip="Remover Arquivo da Fila",
            on_click=self.delete_clicked
        )

        self.status_icon = ft.Icon(ft.icons.PENDING, color=ft.colors.GREY_500, tooltip="Aguardando")

        self.content = ft.Row([
            ft.Container(content=self.lbl_name, expand=True, padding=ft.padding.only(right=10)),
            ft.Container(content=self.lbl_lines, width=70, alignment=ft.alignment.center),
            ft.Container(content=self.dd_source, width=130),
            ft.Container(content=self.dd_comm, width=110),
            ft.Container(content=self.txt_serial, width=120),
            ft.Container(content=self.btn_preview, width=40, alignment=ft.alignment.center),
            ft.Container(content=self.status_icon, width=60, alignment=ft.alignment.center),
            ft.Container(content=self.btn_delete, width=40, alignment=ft.alignment.center)
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def on_source_change(self, e):
        is_telix = self.dd_source.value == "telix"
        self.dd_comm.disabled = not is_telix
        self.txt_serial.disabled = not is_telix
        self.update()

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
        if config["source"] == "telix" and not config["serial"]:
            payload_str = "⚠️ AVISO: Preencha o 'Nº de Série' na tabela antes de visualizar a conversão do Telix."
        else:
            try:
                payloads = preview_data(config["path"], config["source"], config["comm"], config["serial"])
                payload_str = json.dumps(payloads, indent=4, ensure_ascii=False)
            except Exception as ex:
                payload_str = f"❌ Erro na extração:\n{str(ex)}"

        dlg = ft.AlertDialog(
            title=ft.Text(f"Amostra de Payload (Dry Run)", weight=ft.FontWeight.BOLD),
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
        if status == "processing":
            self.status_icon.name = ft.icons.SYNC
            self.status_icon.color = ft.colors.PRIMARY
            self.status_icon.tooltip = "Processando..."
            self.btn_delete.disabled = True
        elif status == "success":
            self.status_icon.name = ft.icons.CHECK_CIRCLE
            self.status_icon.color = ft.colors.GREEN_500
            self.status_icon.tooltip = "Concluído"
            self.btn_delete.disabled = False
        elif status == "error":
            self.status_icon.name = ft.icons.ERROR
            self.status_icon.color = ft.colors.RED_500
            self.status_icon.tooltip = tooltip
            self.btn_delete.disabled = False
        elif status == "cancelled":
            self.status_icon.name = ft.icons.BLOCK
            self.status_icon.color = ft.colors.ORANGE_500
            self.status_icon.tooltip = "Cancelado pelo usuário"
            self.btn_delete.disabled = False
        self.update()


def main_gui(page: ft.Page):
    # Aplica a versão no título da janela
    page.title = f"Telix Sync v{APP_VERSION}"
    page.theme_mode = ft.ThemeMode.DARK

    page.window_icon = "logo.png"
    page.window_width = 1050
    page.window_height = 950
    page.window_min_width = 1050
    page.window_min_height = 800
    page.padding = 20
    page.theme = ft.Theme(color_scheme_seed="#0cbda9")

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.icons.SYNC_ALT),
        leading_width=50,
        # Aplica a versão na barra superior interna
        title=ft.Text(f"Telix Sync v{APP_VERSION}", weight=ft.FontWeight.BOLD),
        center_title=False,
        bgcolor=ft.colors.SURFACE_VARIANT,
        elevation=2,
        actions=[
            ft.Container(
                content=ft.Image(src="auro.png", height=30, fit=ft.ImageFit.CONTAIN),
                padding=ft.padding.only(right=20)
            )
        ]
    )

    file_rows = []
    cancel_token = CancelToken()
    empty_state_text = ft.Text("Nenhum arquivo selecionado.", italic=True, color=ft.colors.GREY_500)
    files_list_view = ft.ListView(spacing=0, height=200, auto_scroll=False)

    def remove_file_from_list(row_to_remove):
        if row_to_remove in file_rows:
            file_rows.remove(row_to_remove)
        if row_to_remove in files_list_view.controls:
            files_list_view.controls.remove(row_to_remove)

        empty_state_text.visible = len(files_list_view.controls) == 0
        page.update()

    def clear_queue(e):
        files_list_view.controls.clear()
        file_rows.clear()
        empty_state_text.visible = True
        page.update()

    def on_files_picked(e: ft.FilePickerResultEvent):
        if e.files:
            existing_paths = [r.filepath for r in file_rows]

            for f in e.files:
                if f.path not in existing_paths:
                    linhas = count_file_lines(f.path)
                    origem_detectada = detect_file_source(f.path)

                    row = FileConfigRow(f.path, linhas, origem_detectada, page, remove_file_from_list)
                    file_rows.append(row)
                    files_list_view.controls.append(row)

            empty_state_text.visible = len(files_list_view.controls) == 0
            page.update()

    file_picker = ft.FilePicker(on_result=on_files_picked)
    page.overlay.append(file_picker)

    saved_type = page.client_storage.get("server_type") or "cloud"
    saved_val = page.client_storage.get("server_val") or ""

    server_type_radio = ft.RadioGroup(
        value=saved_type,
        content=ft.Row([
            ft.Radio(value="cloud", label="Nuvem (Cliente Telix)"),
            ft.Radio(value="local", label="Servidor Interno (IP)")
        ])
    )

    server_input = ft.TextField(value=saved_val, width=400, height=50)

    def apply_server_style():
        if server_type_radio.value == "cloud":
            server_input.label = "Nome do Cliente"
            server_input.prefix_text = "https://"
            server_input.suffix_text = ".telix.com.br"
            server_input.hint_text = "ex: minasgerais"
        else:
            server_input.label = "Endereço IP"
            server_input.prefix_text = "http://"
            server_input.suffix_text = ":8080"
            server_input.hint_text = "ex: 192.168.0.90"

    apply_server_style()

    def handle_server_type_change(e):
        apply_server_style()
        page.update()

    server_type_radio.on_change = handle_server_type_change

    card_server = ft.Card(
        content=ft.Container(
            padding=15,
            content=ft.Column([
                ft.Text("1. Configurações de Conexão", style=ft.TextThemeStyle.TITLE_MEDIUM, weight=ft.FontWeight.BOLD),
                server_type_radio,
                server_input
            ], spacing=10)
        )
    )

    table_header = ft.Container(
        bgcolor=ft.colors.SURFACE_VARIANT,
        padding=ft.padding.symmetric(vertical=10, horizontal=10),
        border_radius=ft.border_radius.only(top_left=8, top_right=8),
        content=ft.Row([
            ft.Container(content=ft.Text("Nome do Arquivo", weight=ft.FontWeight.BOLD), expand=True,
                         padding=ft.padding.only(right=10)),
            ft.Container(content=ft.Text("Linhas", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER), width=70,
                         alignment=ft.alignment.center),
            ft.Container(content=ft.Text("Origem", weight=ft.FontWeight.BOLD), width=130),
            ft.Container(content=ft.Text("Rede", weight=ft.FontWeight.BOLD), width=110),
            ft.Container(content=ft.Text("Série", weight=ft.FontWeight.BOLD), width=120),
            ft.Container(content=ft.Text("Ver", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER), width=40,
                         alignment=ft.alignment.center),
            ft.Container(content=ft.Text("Status", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER), width=60,
                         alignment=ft.alignment.center),
            ft.Container(content=ft.Text("", weight=ft.FontWeight.BOLD), width=40)
        ])
    )

    card_files = ft.Card(
        content=ft.Container(
            padding=15,
            content=ft.Column([
                ft.Row([
                    ft.Text("2. Fila de Processamento", style=ft.TextThemeStyle.TITLE_MEDIUM,
                            weight=ft.FontWeight.BOLD),
                    ft.Row([
                        ft.ElevatedButton("Limpar Fila", icon=ft.icons.DELETE_SWEEP, color=ft.colors.RED_300,
                                          on_click=clear_queue),
                        ft.ElevatedButton("Adicionar Arquivos", icon=ft.icons.ADD_BOX,
                                          on_click=lambda _: file_picker.pick_files(allow_multiple=True,
                                                                                    allowed_extensions=["csv", "txt"]))
                    ], spacing=10)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                table_header,
                ft.Container(
                    content=ft.Column([empty_state_text, files_list_view]),
                    border=ft.border.all(1, ft.colors.OUTLINE_VARIANT),
                    border_radius=ft.border_radius.only(bottom_left=8, bottom_right=8),
                    padding=0
                )
            ])
        )
    )

    log_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    progress_bar = ft.ProgressBar(value=0, visible=False, color=ft.colors.PRIMARY, bgcolor=ft.colors.GREY_800)
    progress_text = ft.Text(value="", visible=False, size=12)

    btn_run = ft.FilledButton(
        "Iniciar Sincronização em Massa",
        icon=ft.icons.PLAY_ARROW,
        height=45,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
    )

    btn_cancel = ft.FilledButton(
        "Cancelar Sincronização",
        icon=ft.icons.STOP,
        height=45,
        disabled=True,
        style=ft.ButtonStyle(
            color=ft.colors.WHITE,
            bgcolor=ft.colors.RED_700,
            shape=ft.RoundedRectangleBorder(radius=8)
        )
    )

    def add_log(msg):
        time_str = datetime.now().strftime('%H:%M:%S')
        log_view.controls.append(ft.Text(f"[{time_str}] {msg}", size=13, font_family="Consolas"))
        log.info(msg)
        page.update()

    def update_progress(current, total):
        progress_bar.value = current / total if total > 0 else 0
        progress_text.value = f"{current} de {total} registros processados do arquivo atual"
        page.update()

    def on_cancel_click(e):
        cancel_token.cancelled = True
        btn_cancel.disabled = True
        add_log("⚠️ Sinal de parada enviado. Aguardando interrupção segura...")
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
        title=ft.Text("Sincronização Concluída!", weight=ft.FontWeight.BOLD),
        content=ft.Text(
            "O lote de arquivos foi processado com sucesso. Verifique os relatórios para detalhes sobre eventuais falhas de conexão."),
        actions=[
            ft.TextButton("Abrir Relatórios", on_click=open_logs_and_close, icon=ft.icons.FOLDER_OPEN,
                          icon_color=ft.colors.PRIMARY),
            ft.TextButton("Ok", on_click=close_success_dlg)
        ]
    )

    async def execute_pipeline(e):
        if not file_rows:
            add_log("ERRO: Adicione pelo menos um arquivo CSV à fila.")
            return

        server_val = server_input.value.strip()
        if not server_val:
            add_log("ERRO: Preencha a configuração de conexão.")
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

        add_log("--- Iniciando Sincronização Telix Sync ---")

        for row in file_rows:
            if cancel_token.cancelled:
                add_log("Lote interrompido. Os arquivos restantes foram cancelados.")
                break

            config = row.get_config()

            if config["source"] == "telix" and not config["serial"]:
                add_log(f"AVISO: Arquivo ignorado: {os.path.basename(config['path'])} (Série não informada)")
                row.set_status("error", "Série pendente")
                continue

            row.set_status("processing")
            add_log(f"> Processando arquivo: {os.path.basename(config['path'])}")

            progress_bar.value = 0
            progress_bar.visible = True
            progress_text.visible = True
            page.update()

            try:
                payloads, token = process_data(
                    file_path=config["path"],
                    source_type=config["source"],
                    comm_type=config["comm"],
                    serial=config["serial"]
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
                    add_log(f"OK: Arquivo {os.path.basename(config['path'])} sincronizado.")

            except PermissionError:
                row.set_status("error", "Bloqueado (Excel/Windows)")
                add_log(
                    f"⚠️ ERRO: O arquivo {os.path.basename(config['path'])} está aberto em outro programa. Feche-o e tente novamente.")
            except Exception as ex:
                row.set_status("error", "Falha interna")
                add_log(f"ERRO em {os.path.basename(config['path'])}: {str(ex)}")

        btn_run.disabled = False
        btn_cancel.disabled = True
        progress_bar.visible = False
        progress_text.visible = False

        log_view.controls.append(
            ft.Row([
                ft.Text("--- Sincronização Concluída ---", size=13, font_family="Consolas"),
                ft.TextButton("Abrir Pasta de Relatórios", icon=ft.icons.FOLDER_OPEN, icon_color=ft.colors.PRIMARY,
                              on_click=lambda _: os.startfile("logs") if os.path.exists("logs") else None)
            ])
        )
        page.update()

        if not cancel_token.cancelled:
            page.dialog = success_dlg
            success_dlg.open = True
            page.update()

    btn_run.on_click = execute_pipeline

    main_layout = ft.Column(
        expand=True,
        controls=[
            card_server,
            card_files,
            ft.Container(
                content=ft.Column([
                    ft.Row([btn_run, btn_cancel], alignment=ft.MainAxisAlignment.CENTER),
                    progress_bar,
                    ft.Row([progress_text], alignment=ft.MainAxisAlignment.CENTER)
                ]),
                padding=ft.padding.symmetric(vertical=5)
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("Terminal de Execução", weight=ft.FontWeight.BOLD, color=ft.colors.GREY_400),
                    log_view
                ], expand=True),
                bgcolor="#1e1e1e",
                border=ft.border.all(1, ft.colors.OUTLINE_VARIANT),
                border_radius=8,
                padding=15,
                expand=True
            )
        ]
    )

    page.add(main_layout)