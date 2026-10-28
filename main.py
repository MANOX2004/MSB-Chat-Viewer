"""WhatsApp export viewer built with CustomTkinter and Pillow."""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import zipfile

import customtkinter as ctk
from PIL import Image

from chat_parser import ChatMessage, ParsedChat, parse_chat_file


COLORS = {
    "sidebar": "#111b21",
    "header": "#202c33",
    "chat": "#0b141a",
    "incoming": "#202c33",
    "outgoing": "#005c4b",
    "green": "#00a884",
    "muted": "#8696a0",
    "text": "#e9edef",
}


def _chat_title(path: Path) -> str:
    title = path.stem.replace("_", " ").strip()
    for prefix in ("WhatsApp Chat with ", "WhatsApp Chat - "):
        if title.casefold().startswith(prefix.casefold()):
            title = title[len(prefix):]
            break
    return title or "WhatsApp Chat"


def _date_label(day: date) -> str:
    today = date.today()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return day.strftime("%B %d, %Y")


class WhatsAppViewer(ctk.CTk):
    """Read-only desktop viewer for exported WhatsApp chats."""

    def __init__(self) -> None:
        super().__init__()
        self.title("WhatsApp Chat Viewer")
        self.geometry("1180x780")
        self.minsize(820, 560)
        self.configure(fg_color=COLORS["chat"])

        self.chat: ParsedChat | None = None
        self.chat_path: Path | None = None
        self.outgoing_name = tk.StringVar(value="Select participant")
        self.date_filter = tk.StringVar(value="All dates")
        self._image_references: list[ctk.CTkImage] = []

        self.grid_columnconfigure(0, weight=0, minsize=260)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_chat_panel()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=260, corner_radius=0, fg_color=COLORS["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="Chats",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=0, padx=22, pady=(28, 22), sticky="w")
        ctk.CTkButton(
            sidebar,
            text="Open Chat (.zip / .txt)",
            command=self._open_chat,
            fg_color=COLORS["green"],
            hover_color="#008f72",
            text_color="#ffffff",
            height=42,
        ).grid(row=1, column=0, padx=18, pady=(0, 26), sticky="ew")

        self._section_label(sidebar, "Select Your Name (Outgoing):", 2)
        self.participant_menu = ctk.CTkOptionMenu(
            sidebar,
            variable=self.outgoing_name,
            values=["Select participant"],
            command=lambda _: self._render_messages(),
            fg_color=COLORS["header"],
            button_color=COLORS["green"],
            button_hover_color="#008f72",
            text_color=COLORS["text"],
            dropdown_fg_color=COLORS["header"],
        )
        self.participant_menu.grid(row=3, column=0, padx=18, pady=(7, 22), sticky="ew")

        self._section_label(sidebar, "Filter by Date:", 4)
        self.date_menu = ctk.CTkOptionMenu(
            sidebar,
            variable=self.date_filter,
            values=["All dates"],
            command=lambda _: self._render_messages(),
            fg_color=COLORS["header"],
            button_color=COLORS["green"],
            button_hover_color="#008f72",
            text_color=COLORS["text"],
            dropdown_fg_color=COLORS["header"],
        )
        self.date_menu.grid(row=5, column=0, padx=18, pady=(7, 12), sticky="new")

        self.info_label = ctk.CTkLabel(
            sidebar,
            text="No chat loaded",
            justify="left",
            anchor="w",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family="Segoe UI", size=13),
        )
        self.info_label.grid(row=6, column=0, padx=20, pady=(8, 24), sticky="ew")

    @staticmethod
    def _section_label(parent: ctk.CTkFrame, text: str, row: int) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        ).grid(row=row, column=0, padx=20, sticky="ew")

    def _build_chat_panel(self) -> None:
        panel = ctk.CTkFrame(self, corner_radius=0, fg_color=COLORS["chat"])
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(panel, height=68, corner_radius=0, fg_color=COLORS["header"])
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="●",
            text_color=COLORS["green"],
            font=ctk.CTkFont(size=32),
        ).grid(row=0, column=0, padx=(20, 12), pady=12)
        self.title_label = ctk.CTkLabel(
            header,
            text="Open an exported chat",
            anchor="w",
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
        )
        self.title_label.grid(row=0, column=1, sticky="ew")
        for column, icon in enumerate(("⌕", "⋮"), start=2):
            ctk.CTkButton(
                header,
                text=icon,
                width=42,
                fg_color="transparent",
                hover_color="#2a3942",
                text_color=COLORS["muted"],
                font=ctk.CTkFont(size=24),
                command=self._show_read_only_notice,
            ).grid(row=0, column=column, padx=(2, 8), pady=12)

        self.messages_frame = ctk.CTkScrollableFrame(
            panel,
            corner_radius=0,
            fg_color=COLORS["chat"],
            scrollbar_button_color="#374248",
            scrollbar_button_hover_color="#4a5960",
        )
        self.messages_frame.grid(row=1, column=0, sticky="nsew")
        self.messages_frame.grid_columnconfigure(0, weight=1)

    def _open_chat(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open WhatsApp chat export",
            filetypes=(("WhatsApp exports", "*.zip *.txt"), ("ZIP archives", "*.zip"), ("Text files", "*.txt")),
        )
        if not selected:
            return
        try:
            parsed = parse_chat_file(selected)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            messagebox.showerror("Could not open chat", str(error), parent=self)
            return

        self.chat_path = Path(selected)
        self.chat = parsed
        self.title_label.configure(text=_chat_title(self.chat_path))
        self.participant_menu.configure(values=["Select participant", *parsed.participants])
        self.outgoing_name.set(parsed.participants[0] if parsed.participants else "Select participant")
        date_values = ["All dates", *(day.isoformat() for day in parsed.dates)]
        self.date_menu.configure(values=date_values)
        self.date_filter.set("All dates")
        self.info_label.configure(
            text=f"{len(parsed.messages):,} messages\n{len(parsed.participants):,} participants"
        )
        self._render_messages()

    def _render_messages(self) -> None:
        for child in self.messages_frame.winfo_children():
            child.destroy()
        self._image_references.clear()

        if self.chat is None:
            self._empty_state("Your exported messages will appear here.")
            return
        selected_date = self.date_filter.get()
        messages = [
            message
            for message in self.chat.messages
            if selected_date == "All dates" or message.timestamp.date().isoformat() == selected_date
        ]
        if not messages:
            self._empty_state("No messages for this date.")
            return

        previous_day: date | None = None
        for message in messages:
            day = message.timestamp.date()
            if day != previous_day:
                self._add_date_pill(_date_label(day))
                previous_day = day
            if message.sender is None:
                self._add_system_notice(message.text)
            else:
                self._add_message(message)
        self.after(30, self._scroll_to_bottom)

    def _empty_state(self, text: str) -> None:
        ctk.CTkLabel(
            self.messages_frame,
            text=text,
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family="Segoe UI", size=15),
        ).grid(row=0, column=0, pady=60, padx=20)

    def _add_date_pill(self, text: str) -> None:
        pill = ctk.CTkLabel(
            self.messages_frame,
            text=text,
            fg_color="#182229",
            corner_radius=14,
            text_color="#c5d1d6",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        pill.grid(row=len(self.messages_frame.winfo_children()), column=0, pady=(18, 12))

    def _add_system_notice(self, text: str) -> None:
        notice = ctk.CTkLabel(
            self.messages_frame,
            text=text or "System notice",
            wraplength=500,
            justify="center",
            fg_color="#182229",
            corner_radius=10,
            text_color="#c5d1d6",
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        notice.grid(row=len(self.messages_frame.winfo_children()), column=0, pady=7, padx=20)

    def _add_message(self, message: ChatMessage) -> None:
        outgoing = message.sender == self.outgoing_name.get()
        bubble = ctk.CTkFrame(
            self.messages_frame,
            corner_radius=12,
            fg_color=COLORS["outgoing"] if outgoing else COLORS["incoming"],
        )
        bubble.grid(
            row=len(self.messages_frame.winfo_children()),
            column=0,
            padx=(70, 18) if outgoing else (18, 70),
            pady=4,
            sticky="e" if outgoing else "w",
        )
        bubble.grid_columnconfigure(0, weight=1)

        show_sender = (
            self.outgoing_name.get() == "Select participant"
            or len(self.chat.participants) > 2
        )
        if show_sender:
            ctk.CTkLabel(
                bubble,
                text=message.sender or "",
                anchor="w",
                text_color=COLORS["green"] if outgoing else "#53bdeb",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            ).grid(row=0, column=0, padx=10, pady=(7, 0), sticky="ew")
        row = 1 if show_sender else 0

        if message.image_data is not None:
            with Image.open(io.BytesIO(message.image_data)) as source:
                source.thumbnail((380, 300))
                image = source.copy()
            photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
            self._image_references.append(photo)
            ctk.CTkLabel(bubble, text="", image=photo).grid(
                row=row, column=0, padx=7, pady=(7, 3), sticky="w"
            )
            row += 1

        if message.text.strip():
            ctk.CTkLabel(
                bubble,
                text=message.text,
                wraplength=480,
                justify="left",
                anchor="w",
                text_color=COLORS["text"],
                font=ctk.CTkFont(family="Segoe UI", size=14),
            ).grid(row=row, column=0, padx=10, pady=(7, 2), sticky="ew")
            row += 1
        elif message.image_data is None:
            ctk.CTkLabel(
                bubble,
                text=" ",
                text_color=COLORS["text"],
            ).grid(row=row, column=0, padx=10, pady=(4, 0), sticky="ew")
            row += 1

        timestamp = ctk.CTkLabel(
            bubble,
            text=message.timestamp.strftime("%I.%M %p").lower(),
            anchor="e",
            text_color="#aebac1",
            font=ctk.CTkFont(family="Segoe UI", size=10),
        )
        timestamp.grid(row=row, column=0, padx=9, pady=(0, 5), sticky="e")
        self._bind_message_context_menu(bubble, message)

    def _bind_message_context_menu(self, widget: tk.Misc, message: ChatMessage) -> None:
        widget.bind(
            "<Button-3>",
            lambda event: self._show_message_datetime(message),
            add="+",
        )
        for child in widget.winfo_children():
            self._bind_message_context_menu(child, message)

    def _show_message_datetime(self, message: ChatMessage) -> None:
        exact_time = message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        messagebox.showinfo("Message date and time", exact_time, parent=self)

    def _scroll_to_bottom(self) -> None:
        self.messages_frame._parent_canvas.yview_moveto(1.0)

    def _show_read_only_notice(self) -> None:
        messagebox.showinfo(
            "Read-only viewer",
            "This app displays exported chats and does not send or modify messages.",
            parent=self,
        )


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("green")
    app = WhatsAppViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
