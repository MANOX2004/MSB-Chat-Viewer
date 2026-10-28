"""WhatsApp export viewer built with CustomTkinter and Pillow."""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import zipfile

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

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


def _emoji_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        is_emoji = (
            0x1F000 <= codepoint <= 0x1FAFF
            or 0x2600 <= codepoint <= 0x27BF
            or 0x2300 <= codepoint <= 0x23FF
            or 0x2B00 <= codepoint <= 0x2BFF
        )
        if not is_emoji:
            index += 1
            continue

        start = index
        index += 1
        if 0x1F1E6 <= codepoint <= 0x1F1FF and index < len(text):
            if 0x1F1E6 <= ord(text[index]) <= 0x1F1FF:
                index += 1
        while index < len(text):
            next_codepoint = ord(text[index])
            if next_codepoint in (0xFE0E, 0xFE0F, 0x20E3) or 0x1F3FB <= next_codepoint <= 0x1F3FF:
                index += 1
            elif next_codepoint == 0x200D and index + 1 < len(text):
                index += 2
            else:
                break
        spans.append((start, index))
    return spans


def _split_trailing_emoji(text: str) -> tuple[str, list[str]]:
    spans = _emoji_spans(text)
    if not spans or text[spans[-1][1]:].strip():
        return text, []

    fonts_dir = Path(r"C:\Windows\Fonts")
    try:
        ImageFont.truetype(str(fonts_dir / "seguiemj.ttf"), 22)
    except OSError:
        return text, []

    first_emoji = len(spans) - 1
    while first_emoji > 0:
        between = text[spans[first_emoji - 1][1]:spans[first_emoji][0]]
        if not between.isspace():
            break
        first_emoji -= 1
    emojis = [text[start:end] for start, end in spans[first_emoji:]]
    return text[:spans[first_emoji][0]].rstrip(), emojis


def _render_emoji_glyph(emoji: str) -> Image.Image | None:
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", 22)
    except OSError:
        return None
    bounds = font.getbbox(emoji)
    if not bounds:
        return None
    image = Image.new(
        "RGBA",
        (max(1, bounds[2] - bounds[0]), max(1, bounds[3] - bounds[1])),
        (0, 0, 0, 0),
    )
    ImageDraw.Draw(image).text(
        (-bounds[0], -bounds[1]),
        emoji,
        font=font,
        embedded_color=True,
    )
    return image


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
        self.search_query = tk.StringVar()
        self._image_references: list[ctk.CTkImage] = []
        self._message_widgets: dict[int, tk.Widget] = {}
        self._search_matches: list[int] = []

        self.grid_columnconfigure(0, weight=0, minsize=260)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_chat_panel()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=260, corner_radius=0, fg_color=COLORS["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(9, weight=1)

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

        self._section_label(sidebar, "Search messages:", 6)
        search_frame = ctk.CTkFrame(sidebar, fg_color=COLORS["header"], corner_radius=8)
        search_frame.grid(row=7, column=0, padx=18, pady=(7, 8), sticky="new")
        search_frame.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self.search_query,
            placeholder_text="Search in chat",
            height=34,
            border_width=0,
            fg_color="transparent",
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["muted"],
        )
        self.search_entry.grid(row=0, column=0, padx=(8, 0), pady=3, sticky="ew")
        self.clear_search_button = ctk.CTkButton(
            search_frame,
            text="×",
            width=26,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#2b3940",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=19),
            command=lambda: self.search_query.set(""),
        )
        self.search_button = ctk.CTkLabel(
            search_frame,
            text="⌕",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=20),
            width=32,
        )
        self.search_button.grid(row=0, column=2, padx=(0, 5), pady=3)
        self.search_query.trace_add("write", self._on_search_changed)
        self.search_status = ctk.CTkLabel(
            sidebar,
            text="",
            anchor="w",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.search_status.grid(row=8, column=0, padx=20, pady=(0, 4), sticky="new")
        self.search_results_frame = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color="#374248",
            scrollbar_button_hover_color="#4a5960",
            height=220,
        )
        self.search_results_frame.grid(row=9, column=0, padx=12, pady=(0, 8), sticky="nsew")
        self.search_results_frame.grid_columnconfigure(0, weight=1)
        self.search_results_frame.grid_remove()

        self.info_label = ctk.CTkLabel(
            sidebar,
            text="No chat loaded",
            justify="left",
            anchor="w",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family="Segoe UI", size=13),
        )
        self.info_label.grid(row=10, column=0, padx=20, pady=(8, 24), sticky="ew")

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
        self.search_query.set("")
        chat_title = _chat_title(self.chat_path)
        self.title_label.configure(text=chat_title)
        self.participant_menu.configure(values=["Select participant", *parsed.participants])
        selected_outgoing = self.outgoing_name.get()
        if selected_outgoing not in parsed.participants:
            selected_outgoing = "Select participant"
            if len(parsed.participants) == 2:
                contact_name = next(
                    (
                        participant
                        for participant in parsed.participants
                        if participant.casefold() == chat_title.casefold()
                    ),
                    None,
                )
                if contact_name is not None:
                    selected_outgoing = next(
                        participant
                        for participant in parsed.participants
                        if participant != contact_name
                    )
        self.outgoing_name.set(selected_outgoing)
        date_values = ["All dates", *(day.isoformat() for day in parsed.dates)]
        self.date_menu.configure(values=date_values)
        self.date_filter.set("All dates")
        identity_hint = (
            f"Showing {selected_outgoing} on the right."
            if selected_outgoing != "Select participant"
            else "Choose your name above to show your messages on the right."
        )
        self.info_label.configure(
            text=(
                f"{len(parsed.messages):,} messages\n"
                f"{len(parsed.participants):,} participants\n"
                f"{identity_hint}"
            )
        )
        self._render_messages()

    def _render_messages(self) -> None:
        for child in self.messages_frame.winfo_children():
            child.destroy()
        self._image_references.clear()
        self._message_widgets.clear()

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
        for message_index, message in enumerate(self.chat.messages):
            if selected_date != "All dates" and message.timestamp.date().isoformat() != selected_date:
                continue
            day = message.timestamp.date()
            if day != previous_day:
                self._add_date_pill(_date_label(day))
                previous_day = day
            if message.sender is None:
                self._add_system_notice(message.text, message_index)
            else:
                self._add_message(message, message_index)
        self.after(30, self._scroll_to_bottom)

    def _on_search_changed(self, *_: str) -> None:
        for child in self.search_results_frame.winfo_children():
            child.destroy()
        self._search_matches.clear()
        raw_query = self.search_query.get()
        if raw_query:
            self.clear_search_button.grid(row=0, column=1, padx=(0, 1), pady=3)
        else:
            self.clear_search_button.grid_remove()

        query = raw_query.strip().casefold()
        if self.chat is None or not query:
            self.search_status.configure(text="")
            self.search_results_frame.grid_remove()
            return

        matches = [
            index
            for index, message in enumerate(self.chat.messages)
            if query in message.text.casefold()
            or query in (message.sender or "").casefold()
        ]
        matches.reverse()
        self._search_matches = matches
        if not matches:
            self.search_status.configure(text="No messages found")
            self.search_results_frame.grid_remove()
            return

        count_label = "result" if len(matches) == 1 else "results"
        self.search_status.configure(text=f"{len(matches)} {count_label}")
        self.search_results_frame.grid()
        for row, message_index in enumerate(matches[:100]):
            message = self.chat.messages[message_index]
            preview = " ".join(message.text.split())
            if not preview and message.attachment_name:
                preview = "Sticker" if Path(message.attachment_name).suffix.casefold() == ".webp" else "Photo"
            if len(preview) > 46:
                preview = f"{preview[:43]}..."

            result = ctk.CTkFrame(
                self.search_results_frame,
                fg_color="#182229",
                corner_radius=10,
            )
            result.grid(row=row, column=0, padx=3, pady=4, sticky="ew")
            result.grid_columnconfigure(0, weight=1)

            tk.Label(
                result,
                text=message.sender or "System",
                anchor="w",
                bg="#182229",
                fg=COLORS["text"],
                font=("Segoe UI", 9, "bold"),
            ).grid(row=0, column=0, padx=(10, 4), pady=(8, 2), sticky="ew")
            tk.Label(
                result,
                text=message.timestamp.strftime("%b %d  ·  %I:%M %p"),
                anchor="e",
                bg="#182229",
                fg=COLORS["muted"],
                font=("Segoe UI", 8),
            ).grid(row=0, column=1, padx=(4, 10), pady=(8, 2), sticky="e")
            tk.Label(
                result,
                text=preview or " ",
                anchor="w",
                bg="#182229",
                fg="#c5d1d6",
                font=("Segoe UI", 9),
            ).grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="ew")
            self._bind_search_result(result, message_index)

        if len(matches) > 100:
            ctk.CTkLabel(
                self.search_results_frame,
                text="Showing first 100 results",
                text_color=COLORS["muted"],
                font=ctk.CTkFont(family="Segoe UI", size=11),
            ).grid(row=100, column=0, pady=6)

    def _bind_search_result(
        self,
        widget: tk.Widget,
        message_index: int,
        card: ctk.CTkFrame | None = None,
    ) -> None:
        if card is None:
            if not isinstance(widget, ctk.CTkFrame):
                raise TypeError("Search result card must be a CustomTkinter frame")
            card = widget
        widget.configure(cursor="hand2")
        widget.bind(
            "<Button-1>",
            lambda event, index=message_index: self._jump_to_message(index),
        )
        widget.bind(
            "<Enter>",
            lambda event, target=card: self._set_search_card_color(target, "#26363f"),
        )
        widget.bind(
            "<Leave>",
            lambda event, target=card: self._set_search_card_color(target, "#182229"),
        )
        for child in widget.winfo_children():
            self._bind_search_result(child, message_index, card)

    @staticmethod
    def _set_search_card_color(widget: tk.Widget, color: str) -> None:
        if isinstance(widget, ctk.CTkFrame):
            widget.configure(fg_color=color)
        else:
            widget.configure(bg=color)
        for child in widget.winfo_children():
            WhatsAppViewer._set_search_card_color(child, color)

    def _jump_to_message(self, message_index: int) -> None:
        if self.chat is None:
            return
        message = self.chat.messages[message_index]
        self.date_filter.set(message.timestamp.date().isoformat())
        self._render_messages()
        self.after(80, lambda: self._focus_message(message_index))

    def _focus_message(self, message_index: int) -> None:
        bubble = self._message_widgets.get(message_index)
        if bubble is None:
            return
        canvas = self.messages_frame._parent_canvas
        content_height = max(1, self.messages_frame._parent_frame.winfo_height())
        target_y = max(0, bubble.winfo_y() - self.messages_frame.winfo_height() // 3)
        canvas.yview_moveto(min(1.0, target_y / content_height))
        bubble.configure(fg_color="#3b4b54")
        self.after(
            1200,
            lambda: bubble.configure(
                fg_color=(
                    "#182229"
                    if self.chat and self.chat.messages[message_index].sender is None
                    else COLORS["outgoing"]
                    if self.chat and self.chat.messages[message_index].sender == self.outgoing_name.get()
                    else COLORS["incoming"]
                )
            )
            if bubble.winfo_exists()
            else None,
        )

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

    def _add_system_notice(self, text: str, message_index: int) -> None:
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
        self._message_widgets[message_index] = notice

    def _add_message(self, message: ChatMessage, message_index: int) -> None:
        outgoing = message.sender == self.outgoing_name.get()
        is_sticker = (
            message.image_data is not None
            and Path(message.attachment_name or "").suffix.casefold() == ".webp"
        )
        has_downloadable_image = message.image_data is not None and not is_sticker
        message_row = len(self.messages_frame.winfo_children())
        row_container = ctk.CTkFrame(
            self.messages_frame,
            fg_color="transparent",
            corner_radius=0,
        )
        row_container.grid(
            row=message_row,
            column=0,
            padx=18,
            pady=4,
            sticky="ew",
        )

        if outgoing:
            row_container.grid_columnconfigure(0, weight=1)
            bubble_column = 2 if has_downloadable_image else 1
            download_column = 1
        else:
            row_container.grid_columnconfigure(2, weight=1)
            bubble_column = 0
            download_column = 1

        bubble = ctk.CTkFrame(
            row_container,
            corner_radius=12,
            fg_color=COLORS["outgoing"] if outgoing else COLORS["incoming"],
        )
        bubble.grid(
            row=0,
            column=bubble_column,
            sticky="e" if outgoing else "w",
        )
        if has_downloadable_image:
            ctk.CTkButton(
                row_container,
                text="↓",
                width=30,
                height=30,
                corner_radius=8,
                fg_color="#111b21",
                hover_color="#26363f",
                text_color=COLORS["text"],
                font=ctk.CTkFont(size=18, weight="bold"),
                command=lambda item=message: self._download_image(item),
            ).grid(
                row=0,
                column=download_column,
                padx=(0, 8) if outgoing else (8, 0),
                sticky="",
            )
        self._message_widgets[message_index] = bubble
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
            ).grid(row=0, column=0, columnspan=2, padx=10, pady=(7, 0), sticky="ew")
        row = 1 if show_sender else 0

        image_row: int | None = None
        if message.image_data is not None and not is_sticker:
            with Image.open(io.BytesIO(message.image_data)) as source:
                source.thumbnail((380, 300))
                image = source.copy()
            photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
            self._image_references.append(photo)
            image_container = ctk.CTkFrame(
                bubble,
                fg_color="transparent",
                corner_radius=8,
            )
            image_container.grid(row=row, column=0, padx=7, pady=(7, 3), sticky="w")
            ctk.CTkLabel(image_container, text="", image=photo).grid(
                row=0, column=0, sticky="nsew"
            )
            image_row = row
            row += 1

        display_text = message.text.strip() or ("Sticker" if is_sticker else "")
        plain_text, trailing_emojis = _split_trailing_emoji(display_text)
        emoji_images = [_render_emoji_glyph(emoji) for emoji in trailing_emojis]
        if any(image is None for image in emoji_images):
            plain_text = display_text
            emoji_images = []

        if plain_text:
            text_font_family = (
                "Nirmala UI"
                if any(0x0D80 <= ord(character) <= 0x0DFF for character in plain_text)
                else "Segoe UI"
            )
            ctk.CTkLabel(
                bubble,
                text=plain_text,
                wraplength=430 if emoji_images else 480,
                justify="left",
                anchor="w",
                text_color=COLORS["text"],
                font=ctk.CTkFont(family=text_font_family, size=14),
            ).grid(row=row, column=0, padx=(10, 4), pady=(7, 2), sticky="w")
            emoji_column = 1
            timestamp_row = row
            timestamp_column = 2 if emoji_images else 1
        elif emoji_images:
            emoji_column = 0
            timestamp_row = row
            timestamp_column = 1
        elif message.image_data is None:
            ctk.CTkLabel(
                bubble,
                text=" ",
                text_color=COLORS["text"],
            ).grid(row=row, column=0, padx=(10, 4), pady=(4, 0), sticky="w")
            timestamp_row = row
            timestamp_column = 1
        else:
            timestamp_row = image_row
            timestamp_column = 1

        if emoji_images:
            emoji_frame = ctk.CTkFrame(bubble, fg_color="transparent", corner_radius=0)
            emoji_frame.grid(row=row, column=emoji_column, padx=(0, 3), pady=(7, 2), sticky="s")
            for index, emoji_image in enumerate(emoji_images):
                if emoji_image is None:
                    continue
                emoji_photo = ctk.CTkImage(
                    light_image=emoji_image,
                    dark_image=emoji_image,
                    size=emoji_image.size,
                )
                self._image_references.append(emoji_photo)
                ctk.CTkLabel(
                    emoji_frame,
                    text="",
                    image=emoji_photo,
                    fg_color="transparent",
                ).grid(row=0, column=index, padx=1, sticky="s")

        timestamp = ctk.CTkLabel(
            bubble,
            text=message.timestamp.strftime("%I.%M %p").lower(),
            anchor="e",
            text_color="#aebac1",
            font=ctk.CTkFont(family="Segoe UI", size=10),
        )
        timestamp.grid(
            row=timestamp_row,
            column=timestamp_column,
            padx=(8, 9),
            pady=(0, 0),
            sticky="se",
        )
        self._bind_message_context_menu(bubble, message)

    def _download_image(self, message: ChatMessage) -> None:
        if message.image_data is None:
            return

        filename = Path(message.attachment_name or "WhatsApp image").name
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            try:
                with Image.open(io.BytesIO(message.image_data)) as image:
                    suffix = {
                        "BMP": ".bmp",
                        "GIF": ".gif",
                        "JPEG": ".jpg",
                        "PNG": ".png",
                        "WEBP": ".webp",
                    }.get((image.format or "").upper(), ".png")
            except (OSError, ValueError) as error:
                messagebox.showerror(
                    "Download image",
                    f"Could not identify the image format:\n{error}",
                    parent=self,
                )
                return
            filename = f"{filename}{suffix}"

        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Download image",
            initialfile=filename,
            defaultextension=suffix,
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not destination:
            return

        try:
            Path(destination).write_bytes(message.image_data)
        except OSError as error:
            messagebox.showerror(
                "Download image",
                f"Could not save the image:\n{error}",
                parent=self,
            )

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
