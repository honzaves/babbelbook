"""
flet_dropdown_test.py — confirmed working pattern: on_select
"""
import flet as ft

def main(page: ft.Page):
    page.title = "Dropdown — on_select works"

    label = ft.Text("Nothing selected yet", size=18)

    def on_select(e):
        label.value = f"{e.control.value} selected"
        page.update()

    dd = ft.Dropdown(
        options=[
            ft.dropdown.Option(key="value1", text="Value 1"),
            ft.dropdown.Option(key="value2", text="Value 2"),
        ],
        width=220,
        on_select=on_select,
    )

    page.add(ft.Row([dd, label], spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER))

ft.run(main)

