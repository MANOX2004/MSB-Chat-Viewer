"""Parse WhatsApp text and ZIP exports without extracting archive contents."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import BinaryIO


_TIME_PATTERN = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?"
_BRACKET_MESSAGE = re.compile(
    rf"^\[(?P<date>\d{{1,4}}[./-]\d{{1,2}}[./-]\d{{2,4}}),\s*"
    rf"(?P<time>{_TIME_PATTERN})\]\s*(?P<body>.*)$"
)
_HYPHEN_MESSAGE = re.compile(
    rf"^(?P<date>\d{{1,4}}[./-]\d{{1,2}}[./-]\d{{2,4}}),?\s+"
    rf"(?P<time>{_TIME_PATTERN})\s+-\s+(?P<body>.*)$"
)
_STICKER_OMITTED = re.compile(r"<\s*sticker\s+omitted\s*>", re.IGNORECASE)
_ATTACHMENT_NAME = re.compile(
    r"(?:<attached:\s*)?([^<>\\/\r\n]+\.(?:jpe?g|png|gif|webp|bmp))\b",
    re.IGNORECASE,
)
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@dataclass(frozen=True)
class ChatMessage:
    """A single exported chat message or system notice."""

    timestamp: datetime
    sender: str | None
    text: str
    attachment_name: str | None = None
    image_data: bytes | None = None


@dataclass(frozen=True)
class ParsedChat:
    """Parsed messages and the distinct participants and calendar dates."""

    messages: list[ChatMessage]
    participants: list[str]
    dates: list[date]


def _decode_text(stream: BinaryIO) -> str:
    content = stream.read()
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


def _parse_timestamp(date_text: str, time_text: str) -> datetime:
    date_text = date_text.strip()
    time_text = re.sub(r"\s+", " ", time_text.strip()).upper()
    date_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%m/%d/%y",
        "%m/%d/%Y",
        "%m.%d.%y",
        "%m.%d.%Y",
        "%d/%m/%y",
        "%d/%m/%Y",
        "%d.%m.%y",
        "%d.%m.%Y",
        "%m-%d-%y",
        "%m-%d-%Y",
        "%d-%m-%y",
        "%d-%m-%Y",
    )
    time_formats = ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p")

    # Resolve unambiguous day-first dates before the common month-first form.
    date_candidates = list(date_formats)
    if re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", date_text):
        first, second = re.split(r"[./-]", date_text)[:2]
        if int(first) > 12:
            date_candidates = [
                "%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y",
                "%d.%m.%y", "%d.%m.%Y",
            ]
        elif int(second) > 12:
            date_candidates = [
                "%m/%d/%y", "%m/%d/%Y", "%m-%d-%y", "%m-%d-%Y",
                "%m.%d.%y", "%m.%d.%Y",
            ]

    parsed_date: date | None = None
    for date_format in date_candidates:
        try:
            parsed_date = datetime.strptime(date_text, date_format).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        raise ValueError(f"Unsupported WhatsApp date: {date_text!r}")

    parsed_time: datetime | None = None
    for time_format in time_formats:
        try:
            parsed_time = datetime.strptime(time_text, time_format)
            break
        except ValueError:
            continue
    if parsed_time is None:
        raise ValueError(f"Unsupported WhatsApp time: {time_text!r}")

    return datetime.combine(parsed_date, parsed_time.time())


def _message_start(line: str) -> tuple[datetime, str] | None:
    for pattern in (_BRACKET_MESSAGE, _HYPHEN_MESSAGE):
        match = pattern.match(line)
        if match is None:
            continue
        try:
            timestamp = _parse_timestamp(match.group("date"), match.group("time"))
        except ValueError:
            continue
        return timestamp, match.group("body")
    return None


def _split_sender(body: str) -> tuple[str | None, str]:
    match = re.match(r"^\s*(?P<sender>[^:：\r\n]+?)\s*[:：]\s*(?P<text>.*)$", body, re.DOTALL)
    if match is not None and match.group("sender").strip():
        return match.group("sender").strip(), match.group("text")
    return None, body


def _clean_sticker_text(text: str) -> str:
    cleaned = _STICKER_OMITTED.sub("Sticker", text)
    return re.sub(r"(?<!\w)sticker omitted(?!\w)", "Sticker", cleaned, flags=re.IGNORECASE)


def _image_for_text(
    text: str, images: dict[str, tuple[str, bytes]]
) -> tuple[str | None, bytes | None]:
    for match in _ATTACHMENT_NAME.finditer(text):
        filename = match.group(1).strip()
        image = images.get(Path(filename).name.casefold())
        if image is not None:
            return image
    return None, None


def _parse_lines(text: str, images: dict[str, tuple[str, bytes]]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    current_timestamp: datetime | None = None
    current_body: list[str] = []

    def flush() -> None:
        if current_timestamp is None:
            return
        body = _clean_sticker_text("\n".join(current_body).strip())
        sender, message_text = _split_sender(body)
        attachment_name, image_data = _image_for_text(message_text, images)
        messages.append(
            ChatMessage(
                timestamp=current_timestamp,
                sender=sender,
                text=message_text,
                attachment_name=attachment_name,
                image_data=image_data,
            )
        )

    for line in text.splitlines():
        parsed = _message_start(line)
        if parsed is not None:
            flush()
            current_timestamp, body = parsed
            current_body = [body]
        elif current_timestamp is not None:
            current_body.append(line)
    flush()
    return messages


def _images_from_zip(archive: zipfile.ZipFile) -> dict[str, tuple[str, bytes]]:
    images: dict[str, tuple[str, bytes]] = {}
    for member in archive.infolist():
        if member.is_dir() or Path(member.filename).suffix.casefold() not in _IMAGE_SUFFIXES:
            continue
        name = Path(member.filename).name
        images[name.casefold()] = (name, archive.read(member))
    return images


def parse_chat_file(file_path: str | Path) -> ParsedChat:
    """Parse a WhatsApp .txt or .zip export and return messages plus metadata.

    ZIP entries are read directly and never extracted to the filesystem. For
    archives containing multiple text files, the first sorted .txt is used.
    """

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Chat export not found: {path}")

    if path.suffix.casefold() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                text_files = sorted(
                    (member for member in archive.namelist() if member.casefold().endswith(".txt")),
                    key=str.casefold,
                )
                if not text_files:
                    raise ValueError("The ZIP archive does not contain a .txt chat export.")
                with archive.open(text_files[0]) as stream:
                    text = _decode_text(stream)
                images = _images_from_zip(archive)
        except zipfile.BadZipFile as error:
            raise ValueError(f"Invalid ZIP archive: {path.name}") from error
        except RuntimeError as error:
            raise ValueError(f"Unable to read ZIP archive: {error}") from error
    elif path.suffix.casefold() == ".txt":
        with path.open("rb") as stream:
            text = _decode_text(stream)
        images = {}
    else:
        raise ValueError("Choose a WhatsApp .zip or .txt export.")

    messages = _parse_lines(text, images)
    participants = sorted({message.sender for message in messages if message.sender})
    dates = sorted({message.timestamp.date() for message in messages})
    return ParsedChat(messages=messages, participants=participants, dates=dates)
