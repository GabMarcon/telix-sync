import flet as ft
from src.gui.app_flet import main_gui

if __name__ == "__main__":
    # O assets_dir é crucial para carregar a logo!
    ft.app(target=main_gui, assets_dir="assets")