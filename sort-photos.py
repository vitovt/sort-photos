#!/usr/bin/env python3

import os
import shutil
import re
import sys
from tkinter import Tk, Label
from PIL import Image, ImageTk, ImageDraw
from collections import deque

try:
    import vlc
except ImportError:
    vlc = None

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.wmv', '.mpg', '.mpeg', '.flv', '.webm', '.3gp')
VIDEO_SCRUB_STEP_MS = 5000


def _normalize_sort_mode(value):
    cleaned = re.sub(r"[^a-z0-9]", "", value.lower())
    return cleaned


NATURAL_CHUNK_RE = re.compile(r"(\d+)")

# Спрощені варіанти сортування з короткими ключами
SORT_MODE_VARIANTS = [
    ("name", "За назвою (А-Я)", {"type": "alpha", "reverse": False}),
    ("name-rev", "За назвою (Я-А)", {"type": "alpha", "reverse": True}),
    ("natural", "Натуральне сортування (1,2,10)", {"type": "natural", "reverse": False}),
    ("natural-rev", "Натуральне сортування (10,2,1)", {"type": "natural", "reverse": True}),
    ("created", "За датою створення (старі→нові)", {"type": "stat", "attribute": "st_ctime", "reverse": False}),
    ("created-rev", "За датою створення (нові→старі)", {"type": "stat", "attribute": "st_ctime", "reverse": True}),
    ("modified", "За датою зміни (старі→нові)", {"type": "stat", "attribute": "st_mtime", "reverse": False}),
    ("modified-rev", "За датою зміни (нові→старі)", {"type": "stat", "attribute": "st_mtime", "reverse": True}),
    ("size", "За розміром (менші→більші)", {"type": "stat", "attribute": "st_size", "reverse": False}),
    ("size-rev", "За розміром (більші→менші)", {"type": "stat", "attribute": "st_size", "reverse": True}),
]

SORT_MODE_INFO = {}
SORT_MODE_LOOKUP = {}
for key, label, config in SORT_MODE_VARIANTS:
    SORT_MODE_INFO[key] = {"label": label, **config}
    SORT_MODE_LOOKUP[_normalize_sort_mode(key)] = key
    SORT_MODE_LOOKUP[_normalize_sort_mode(label)] = key

class PhotoSorterApp:
    """
    Основний клас програми для сортування медіафайлів.
    Дозволяє переміщувати або копіювати фото та відео до кількох тек,
    підтримує різні режими сортування та показує відео з аудіо
    (через VLC, якщо доступний).
    """
    def __init__(self, master, source_dir, destination_dirs, transfer_mode="move", sort_mode="name", filetypes="all"):
        self.master = master
        self.master.title("Сортувальник Фотографій")
        # Встановлюємо початковий розмір вікна.
        # Розмір може бути змінений користувачем.
        self.master.geometry("800x600")
        # Прив'язуємо обробник подій клавіш до всього вікна.
        self.master.bind("<Key>", self.on_key_press)
        # Додаємо обробник подій зміни розміру вікна для адаптації зображення.
        self.master.bind("<Configure>", self.on_resize)

        # Перетворюємо шляхи на абсолютні для уникнення проблем
        self.source_dir = os.path.abspath(source_dir)
        self.transfer_mode = transfer_mode
        self.sort_mode = sort_mode
        self.sort_mode_label = SORT_MODE_INFO[self.sort_mode]["label"]
        self.filetypes = filetypes
        self.vlc_available = vlc is not None
        self.vlc_instance = vlc.Instance("--quiet") if self.vlc_available else None
        self.vlc_player = None
        self.video_status_job = None
        self.current_media_type = None
        self.current_media_path = None
        self.current_status_header = ""
        self.current_instruction_text = ""
        self.video_duration_ms = 0
        self.video_paused = False

        destination_dirs = [os.path.abspath(path) for path in destination_dirs]
        if len(destination_dirs) < 2:
            raise ValueError("Потрібно вказати щонайменше дві цільові теки призначення.")

        self.destination_options = []
        for index, dest in enumerate(destination_dirs):
            key = self._generate_hotkey(index)
            label = self._format_destination_label(dest)
            self.destination_options.append((key, dest, label))
            # Створення цільових директорій, якщо вони не існують.
            # exist_ok=True запобігає помилці, якщо тека вже є.
            os.makedirs(dest, exist_ok=True)

        self.key_to_destination = {key: dest for key, dest, _ in self.destination_options}
        self.destination_labels = {dest: label for _, dest, label in self.destination_options}
        self.destination_instruction_text = ", ".join(
            [f"'{key}' для {label}" for key, _, label in self.destination_options]
        )

        # Збираємо всі файли з вихідної директорії та її підтек.
        self.photo_files = self._get_all_media_files()
        # Список впорядковується згідно з параметром sort_mode.
        self.current_photo_index = -1 # Індекс поточного об'єкта, load_next_photo зробить його 0.

        # Створюємо мітку для відображення зображення.
        # expand=True та fill="both" дозволяють мітці займати весь доступний простір.
        self.image_label = Label(master, bg="lightgray")
        self.image_label.pack(expand=True, fill="both")

        # Створюємо мітку для відображення статусу та інструкцій.
        self.status_label = Label(master, text="Завантаження...", font=("Arial", 12), wraplength=750)
        self.status_label.pack(side="bottom", pady=10)

        # Показуємо діагностичну інформацію
        self._show_diagnostic_info()

        # Даємо час вікну для ініціалізації
        self.master.after(100, self.load_next_photo)

    def _show_diagnostic_info(self):
        """
        Показує діагностичну інформацію про знайдені файли
        """
        print(f"Пошук файлів у директорії: {self.source_dir}")
        print(f"Директорія існує: {os.path.exists(self.source_dir)}")
        print(f"Це директорія: {os.path.isdir(self.source_dir)}")

        if os.path.exists(self.source_dir):
            print(f"Вміст директорії:")
            try:
                for item in os.listdir(self.source_dir):
                    item_path = os.path.join(self.source_dir, item)
                    if os.path.isfile(item_path):
                        print(f"  ФАЙЛ: {item}")
                    elif os.path.isdir(item_path):
                        print(f"  ТЕКА: {item}")
            except PermissionError:
                print("  Помилка доступу до директорії")

        print(f"Знайдено підтримуваних медіафайлів: {len(self.photo_files)}")
        print(f"Режим сортування: {self.sort_mode_label}")
        if not self.vlc_available:
            print("Увага: python-vlc не знайдено — відео відображатиметься без відтворення.")
        if len(self.photo_files) > 0:
            print("Перші 5 знайдених файлів:")
            for i, file in enumerate(list(self.photo_files)[:5]):
                print(f"  {i+1}. {file}")

    def _get_all_media_files(self):
        """
        Рекурсивно збирає всі підтримувані фото та відео з вихідної директорії,
        включно з підтек, та повертає відсортований список.
        Після збирання застосовується обраний режим сортування.
        """
        image_extensions = IMAGE_EXTENSIONS
        video_extensions = VIDEO_EXTENSIONS
        include_photos = self.filetypes in ("all", "photo")
        include_videos = self.filetypes in ("all", "video")
        all_files = deque() # Використовуємо deque для ефективного додавання/видалення

        active_extensions = ()
        if include_photos:
            active_extensions += image_extensions
        if include_videos:
            active_extensions += video_extensions

        print(f"Пошук файлів із розширеннями: {active_extensions if active_extensions else 'немає (фільтр вимкнув усі типи)'}")

        try:
            for root, dirs, files in os.walk(self.source_dir):
                print(f"Перевіряю теку: {root}")
                for file in files:
                    file_lower = file.lower()
                    if include_photos and file_lower.endswith(image_extensions):
                        full_path = os.path.join(root, file)
                        all_files.append(full_path)
                        print(f"  Знайдено фото: {file}")
                    elif include_videos and file_lower.endswith(video_extensions):
                        full_path = os.path.join(root, file)
                        all_files.append(full_path)
                        print(f"  Знайдено відео: {file}")
                    else:
                        print(f"  Пропущено: {file} (не підтримується)")
        except Exception as e:
            print(f"Помилка під час пошуку файлів: {e}")

        file_list = list(all_files)
        return self._sort_photo_list(file_list)

    def _generate_hotkey(self, index):
        """
        Генерує гарячу клавішу для відповідної цільової теки.
        Спочатку використовуються цифри, після дев'яти тек переходить до літер латиниці.
        """
        if index < 9:
            return str(index + 1)
        ascii_code = ord('A') + (index - 9)
        if ascii_code > ord('Z'):
            raise ValueError("Підтримується до 35 цільових тек.")
        return chr(ascii_code)

    def _format_destination_label(self, path):
        """
        Повертає назву теки без повного шляху для показу користувачу.
        """
        cleaned = path.rstrip(os.sep)
        base = os.path.basename(cleaned)
        return base if base else cleaned

    def _is_supported_image(self, path):
        return path.lower().endswith(IMAGE_EXTENSIONS)

    def _is_supported_video(self, path):
        return path.lower().endswith(VIDEO_EXTENSIONS)

    def _create_placeholder_image(self, title, subtitle=""):
        """
        Створює простий заглушковий кадр із текстом.
        """
        width, height = 800, 600
        img = Image.new("RGB", (width, height), color=(45, 45, 45))
        draw = ImageDraw.Draw(img)
        message = title if not subtitle else f"{title}\n{subtitle}"
        tw, th = draw.multiline_textsize(message, spacing=8)
        draw.multiline_text(
            ((width - tw) / 2, (height - th) / 2),
            message,
            fill=(255, 255, 255),
            align="center",
            spacing=8,
        )
        return img

    def _load_image_preview(self, path):
        """
        Повертає копію зображення або заглушку у випадку помилки.
        """
        try:
            with Image.open(path) as img:
                return img.copy()
        except Exception as exc:
            print(f"Не вдалося завантажити {path}: {exc}")
            return self._create_placeholder_image("Помилка зображення", os.path.basename(path))

    def _show_pil_image(self, pil_image, max_width, max_height):
        """
        Масштабує та показує PIL.Image у віджеті.
        """
        img = pil_image.copy()
        img.thumbnail((max_width, max_height), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(img)
        self.image_label.config(image=self.photo, text="")
        self.image_label.image = self.photo

    def _build_instruction_text(self, media_kind):
        base = f"Натисніть {self.destination_instruction_text}, 'S' для пропуску, 'Q' для виходу."
        if media_kind == "Відео":
            base += " Пробіл — пауза/продовжити, \u2190/\u2192 — перемотка 5с."
        return base

    def _set_status_text(self, header, extra_line=""):
        """
        Оновлює текст статусу з урахуванням основного повідомлення та інструкцій.
        """
        parts = [header]
        if extra_line:
            parts.append(extra_line)
        parts.append(self.current_instruction_text)
        self.status_label.config(text="\n".join(parts))

    def _format_timestamp(self, millis):
        if millis <= 0:
            return "00:00"
        seconds = millis // 1000
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02}:{minutes:02}:{sec:02}"
        return f"{minutes:02}:{sec:02}"

    def _ensure_vlc_player(self):
        if not self.vlc_available:
            return None
        if self.vlc_instance is None:
            self.vlc_instance = vlc.Instance("--quiet")
        self._stop_video_playback()
        return self.vlc_instance.media_player_new()

    def _attach_player_to_widget(self, player):
        widget_id = self.image_label.winfo_id()
        if sys.platform.startswith("linux"):
            player.set_xwindow(widget_id)
        elif sys.platform == "win32":
            player.set_hwnd(widget_id)
        elif sys.platform == "darwin":
            player.set_nsobject(widget_id)

    def _play_video(self, path):
        """
        Запускає відео у віджеті. Повертає True, якщо відтворення стартувало.
        """
        if not self.vlc_available:
            return False

        player = self._ensure_vlc_player()
        if player is None:
            return False

        media = self.vlc_instance.media_new(path)
        player.set_media(media)
        self.master.update_idletasks()
        self._attach_player_to_widget(player)
        result = player.play()
        if result == -1:
            self._stop_video_playback()
            return False

        self.vlc_player = player
        self.video_paused = False
        self.video_duration_ms = 0
        self._schedule_video_status_update()
        return True

    def _schedule_video_status_update(self):
        if self.video_status_job is not None:
            self.master.after_cancel(self.video_status_job)
        self.video_status_job = self.master.after(500, self._update_video_status)

    def _update_video_status(self):
        if not self.vlc_player:
            return
        current = self.vlc_player.get_time()
        total = self.vlc_player.get_length()
        if total and total > 0:
            self.video_duration_ms = total
        total = self.video_duration_ms
        progress = f"{self._format_timestamp(current)} / {self._format_timestamp(total)}" if total else ""
        header = self.current_status_header
        self._set_status_text(header, progress)
        self._schedule_video_status_update()

    def _stop_video_playback(self):
        if self.video_status_job is not None:
            try:
                self.master.after_cancel(self.video_status_job)
            except Exception:
                pass
        self.video_status_job = None
        if self.vlc_player is not None:
            try:
                self.vlc_player.stop()
            except Exception:
                pass
        self.vlc_player = None
        self.video_duration_ms = 0
        self.video_paused = False

    def _vlc_ready(self):
        return self.vlc_player is not None

    def _seek_video(self, delta_ms):
        if not self._vlc_ready():
            return
        player = self.vlc_player
        current = player.get_time()
        length = player.get_length()
        target = current + delta_ms
        if length and length > 0:
            target = max(0, min(target, length))
        else:
            target = max(0, target)

        def apply_seek():
            if not self._vlc_ready():
                return
            self.vlc_player.set_time(int(target))
            if self.video_paused:
                self.vlc_player.set_pause(1)

        state = player.get_state()
        restart_needed = (
            length and target < length and state in (vlc.State.Ended, vlc.State.Stopped)
        )

        if restart_needed:
            player.stop()
            result = player.play()
            self.video_paused = False
            delay = 150 if result == 0 else 0
            self.master.after(delay, apply_seek)
        else:
            apply_seek()

    def _toggle_video_pause(self):
        if not self._vlc_ready():
            return
        self.vlc_player.pause()
        self.video_paused = not self.video_paused

    def _sort_photo_list(self, files):
        """
        Сортує список файлів згідно з обраним режимом.
        """
        config = SORT_MODE_INFO.get(self.sort_mode, SORT_MODE_INFO["name"])
        reverse = config.get("reverse", False)
        sort_type = config.get("type")

        if sort_type == "alpha":
            key_func = lambda path: os.path.basename(path).lower()
        elif sort_type == "natural":
            key_func = lambda path: self._natural_key(os.path.basename(path))
        elif sort_type == "stat":
            attribute = config.get("attribute")
            key_func = lambda path: self._get_stat_value(path, attribute)
        else:
            key_func = lambda path: os.path.basename(path).lower()

        sorted_files = sorted(files, key=key_func, reverse=reverse)
        return sorted_files

    def _natural_key(self, text):
        """
        Формує натуральний ключ сортування для тексту.
        """
        return [int(chunk) if chunk.isdigit() else chunk.lower() for chunk in NATURAL_CHUNK_RE.split(text)]

    def _get_stat_value(self, path, attribute):
        """
        Безпечно отримує значення st_* для шляху, повертаючи 0 при помилці.
        """
        try:
            stat_result = os.stat(path)
            return getattr(stat_result, attribute, 0)
        except (FileNotFoundError, PermissionError, OSError):
            return 0

    def on_resize(self, event):
        """
        Обробник події зміни розміру вікна.
        Перезавантажує поточне фото, щоб воно адаптувалося до нового розміру вікна.
        """
        # Перевіряємо, чи це подія зміни розміру вікна, а не інша подія Configure.
        if event.widget == self.master and hasattr(self, 'current_photo_index'):
            # Перезавантажуємо поточне фото, щоб воно підлаштувалося під новий розмір.
            # Зменшуємо індекс на 1, щоб load_next_photo завантажила те ж саме фото.
            if self.current_photo_index >= 0:
                self.current_photo_index -= 1
                self.load_next_photo()

    def load_next_photo(self):
        """
        Завантажує та відображає наступний медіафайл зі списку.
        Адаптує попередній перегляд до розміру вікна.
        """
        self._stop_video_playback()
        self.current_photo_index += 1
        if self.current_photo_index < len(self.photo_files):
            current_file_path = self.photo_files[self.current_photo_index]
            media_kind = "Відео" if self._is_supported_video(current_file_path) else "Фото"
            self.current_media_type = media_kind
            self.current_media_path = current_file_path
            self.current_instruction_text = self._build_instruction_text(media_kind)
            self.current_status_header = (
                f"{media_kind}: {os.path.basename(current_file_path)} "
                f"({self.current_photo_index + 1}/{len(self.photo_files)})"
            )
            self._set_status_text(self.current_status_header, "" if media_kind == "Фото" else "Завантаження...")
            try:
                self.master.update_idletasks()
                window_width = self.master.winfo_width()
                window_height = self.master.winfo_height()
                if window_width <= 1 or window_height <= 1:
                    window_width = 800
                    window_height = 600
                status_height = self.status_label.winfo_reqheight() if self.status_label.winfo_reqheight() > 0 else 60
                max_img_width = max(100, window_width - 40)  # Відступи, мінімум 100px
                max_img_height = max(100, window_height - status_height - 40)  # Відступи та висота статус-бару, мінімум 100px
                print(f"Розміри вікна: {window_width}x{window_height}, макс. розмір попереднього перегляду: {max_img_width}x{max_img_height}")

                if media_kind == "Відео" and self.vlc_available:
                    self.image_label.config(image="", text="Завантаження відео...")
                    started = self._play_video(current_file_path)
                    if not started:
                        placeholder = self._create_placeholder_image("Не вдалося відтворити відео", os.path.basename(current_file_path))
                        self._show_pil_image(placeholder, max_img_width, max_img_height)
                        self._set_status_text(self.current_status_header, "Помилка відтворення")
                else:
                    if media_kind == "Відео" and not self.vlc_available:
                        img = self._create_placeholder_image("Встановіть python-vlc", os.path.basename(current_file_path))
                    else:
                        img = self._load_image_preview(current_file_path)
                    self._show_pil_image(img, max_img_width, max_img_height)
                    self._set_status_text(self.current_status_header)

                self.master.focus_force()
            except Exception as e:
                self.status_label.config(text=f"Помилка завантаження {os.path.basename(current_file_path)}: {e}\nПропускаю...")
                print(f"Помилка завантаження {current_file_path}: {e}")
                self.load_next_photo()
        else:
            # Якщо всі фотографії відсортовано або немає фотографій.
            if len(self.photo_files) == 0:
                supported_images = ", ".join(IMAGE_EXTENSIONS)
                supported_videos = ", ".join(VIDEO_EXTENSIONS)
                self.status_label.config(
                    text=("Не знайдено жодного підтримуваного медіафайлу у вказаній директорії!\n"
                          f"Зображення: {supported_images}\n"
                          f"Відео: {supported_videos}")
                )
                self.image_label.config(text="Файли не знайдено", image="")
            else:
                self.status_label.config(text="Усі медіафайли відсортовано! Завершення.")
                # Закриваємо вікно через 3 секунди.
                self.master.after(3000, self.master.destroy)

    def on_key_press(self, event):
        """
        Обробник натискання клавіш.
        Визначає дію залежно від натиснутої клавіші.
        """
        key = event.char.upper() if event.char else ""
        keysym = event.keysym.upper()
        if self.current_photo_index >= len(self.photo_files):
            return # Не обробляти, якщо всі медіафайли відсортовано

        current_file_path = self.photo_files[self.current_photo_index]
        is_video = self.current_media_type == "Відео"

        if key in self.key_to_destination:
            self._move_photo(current_file_path, self.key_to_destination[key])
        elif key == 'S': # Пропустити фотографію
            self._stop_video_playback()
            self.status_label.config(text=f"Пропущено: {os.path.basename(current_file_path)}")
            self.master.update_idletasks() # Оновлюємо інтерфейс, щоб показати статус
            self.load_next_photo()
            return
        elif key == 'Q': # Вихід з програми
            self._stop_video_playback()
            self.master.destroy()
            return
        elif keysym == "SPACE" and is_video:
            self._toggle_video_pause()
            return
        elif keysym == "LEFT" and is_video:
            self._seek_video(-VIDEO_SCRUB_STEP_MS)
            return
        elif keysym == "RIGHT" and is_video:
            self._seek_video(VIDEO_SCRUB_STEP_MS)
            return
        else:
            self.status_label.config(
                text=f"Невідома клавіша. Використовуйте {self.destination_instruction_text}, 'S' або 'Q'."
            )
            return # Не завантажуємо наступне фото, якщо була неправильна клавіша

        # Завантажуємо наступне фото після успішної обробки (переміщення або пропуску).
        self.load_next_photo()

    def _move_photo(self, source_path, destination_base_dir):
        """
        Переміщує або копіює медіафайл з 'source_path' до 'destination_base_dir',
        зберігаючи при цьому відносну ієрархію тек.
        Наприклад, якщо source_dir=/src, source_path=/src/a/b/c.jpg,
        destination_base_dir=/dest, то файл буде переміщено до /dest/a/b/c.jpg.
        """
        # Обчислюємо відносний шлях файлу відносно вихідної директорії.
        relative_path = os.path.relpath(source_path, self.source_dir)
        # Формуємо повний шлях до цільового файлу.
        destination_path = os.path.join(destination_base_dir, relative_path)
        # Отримуємо шлях до цільової теки для цього файлу.
        destination_dir = os.path.dirname(destination_path)

        try:
            # Створюємо батьківські теки в цільовій директорії, якщо їх немає.
            os.makedirs(destination_dir, exist_ok=True)
            # Переміщуємо або копіюємо файл залежно від обраного режиму.
            if self.transfer_mode == "copy":
                shutil.copy2(source_path, destination_path)
                action = "Скопійовано"
            else:
                shutil.move(source_path, destination_path)
                action = "Переміщено"
            human_readable_dest = self.destination_labels.get(destination_base_dir, os.path.basename(destination_base_dir))
            self.status_label.config(text=f"{action}: {os.path.basename(source_path)} до {human_readable_dest}")
            print(f"{action}: {source_path} -> {destination_path}")
        except Exception as e:
            # Обробка помилок під час переміщення або копіювання файлу.
            self.status_label.config(text=f"Помилка обробки {os.path.basename(source_path)}: {e}")
            print(f"Помилка обробки {source_path}: {e}")

if __name__ == "__main__":
    def print_usage():
        print("Використання: python sort-photos.py [--mode move|copy] [--sort <режим>] <вихідна_тека> <тека_1> <тека_2> [тека_3 ...]")
        print()
        print("Параметри:")
        print("  --mode       Режим роботи: 'move' (переміщення) або 'copy' (копіювання)")
        print("               За замовчуванням: move")
        print("  --sort       Режим сортування (див. нижче)")
        print("               За замовчуванням: name")
        print("  --filetypes  Які типи медіа брати: 'photo', 'video' або 'all'")
        print("               За замовчуванням: all")
        print()
        print("Доступні режими сортування (--sort):")
        for key, label, _ in SORT_MODE_VARIANTS:
            print(f"  {key:15} - {label}")
        print("Підтримуються фото та відео. Для відтворення відео з аудіо необхідно встановити VLC / python-vlc.")
        print("Під час перегляду відео використовуйте пробіл для паузи, \u2190/\u2192 для перемотки (5с).")
        print()
        print("Приклади:")
        print("  # Базове використання (переміщення, сортування за назвою)")
        print("  python sort-photos.py /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print()
        print("  # Копіювання замість переміщення")
        print("  python sort-photos.py --mode copy /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print()
        print("  # Сортування за датою створення (нові спочатку)")
        print("  python sort-photos.py --sort created-rev /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print()
        print("  # Натуральне сортування з копіюванням")
        print("  python sort-photos.py --mode copy --sort natural /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print()
        print("  # Працювати тільки з фото")
        print("  python sort-photos.py --filetypes photo /home/user/Фото_НовийРік /home/user/СвяткуємоНР /home/user/Фото_Прибирання")
        print()
        print("  # Працювати тільки з відео")
        print("  python sort-photos.py --filetypes video /home/user/УсіМедіа /home/user/Відео_YT /home/user/Відео_Сім\'я")
        print()
        print("  # Сортування за розміром (більші спочатку)")
        print("  python sort-photos.py --sort size-rev /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print()
        print("  # Windows приклад")
        print("  python sort-photos.py --mode copy --sort modified C:\\Photos C:\\Photos_Person1 C:\\Photos_Person2")

    args = sys.argv[1:]
    mode = "move"
    sort_mode_key = "name"
    filetype_filter = "all"
    positional_args = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--mode"):
            if arg == "--mode":
                if i + 1 >= len(args):
                    print("Помилка: після --mode потрібно вказати 'move' або 'copy'.")
                    print_usage()
                    sys.exit(1)
                mode = args[i + 1].lower()
                i += 2
            else:
                _, _, value = arg.partition("=")
                if not value:
                    print("Помилка: використовуйте '--mode copy' або '--mode=copy'.")
                    print_usage()
                    sys.exit(1)
                mode = value.lower()
                i += 1
            if mode not in ("move", "copy"):
                print("Помилка: режим має бути 'move' або 'copy'.")
                print_usage()
                sys.exit(1)
        elif arg.startswith("--sort"):
            if arg == "--sort":
                if i + 1 >= len(args):
                    print("Помилка: після --sort потрібно вказати один із документованих режимів.")
                    print_usage()
                    sys.exit(1)
                sort_value = args[i + 1]
                i += 2
            else:
                _, _, sort_value = arg.partition("=")
                if not sort_value:
                    print("Помилка: використовуйте '--sort name' або '--sort=name'.")
                    print_usage()
                    sys.exit(1)
                i += 1
            normalized = _normalize_sort_mode(sort_value)
            if normalized not in SORT_MODE_LOOKUP:
                print(f"Помилка: невідомий режим сортування '{sort_value}'.")
                print_usage()
                sys.exit(1)
            sort_mode_key = SORT_MODE_LOOKUP[normalized]
        elif arg.startswith("--filetypes"):
            if arg == "--filetypes":
                if i + 1 >= len(args):
                    print("Помилка: після --filetypes потрібно вказати 'photo', 'video' або 'all'.")
                    print_usage()
                    sys.exit(1)
                filetypes_value = args[i + 1]
                i += 2
            else:
                _, _, filetypes_value = arg.partition("=")
                if not filetypes_value:
                    print("Помилка: використовуйте '--filetypes photo' або '--filetypes=photo'.")
                    print_usage()
                    sys.exit(1)
                i += 1
            normalized_ft = filetypes_value.lower()
            if normalized_ft not in ("photo", "video", "all"):
                print("Помилка: --filetypes підтримує лише значення 'photo', 'video' або 'all'.")
                print_usage()
                sys.exit(1)
            filetype_filter = normalized_ft
        elif arg in ("-h", "--help"):
            print_usage()
            sys.exit(0)
        else:
            positional_args.append(arg)
            i += 1

    if len(positional_args) < 3:
        print_usage()
        sys.exit(1)

    # Отримуємо шляхи з аргументів командного рядка.
    source_directory = positional_args[0]
    destination_directories = positional_args[1:]

    if len(destination_directories) < 2:
        print("Помилка: потрібно вказати щонайменше дві цільові теки.")
        sys.exit(1)

    # Перевіряємо, чи існує вихідна директорія.
    if not os.path.exists(source_directory):
        print(f"Помилка: Вихідна директорія '{source_directory}' не існує.")
        sys.exit(1)

    if not os.path.isdir(source_directory):
        print(f"Помилка: '{source_directory}' не є директорією.")
        sys.exit(1)

    # Ініціалізуємо головне вікно Tkinter.
    root = Tk()
    # Створюємо екземпляр програми.
    app = PhotoSorterApp(root, source_directory, destination_directories, transfer_mode=mode, sort_mode=sort_mode_key, filetypes=filetype_filter)
    # Запускаємо головний цикл подій Tkinter.
    root.mainloop()
