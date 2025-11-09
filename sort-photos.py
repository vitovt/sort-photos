#!/usr/bin/env python3

import os
import shutil
import re
from tkinter import Tk, Label, PhotoImage
from PIL import Image, ImageTk, ImageDraw
from collections import deque
import sys

try:
    import cv2
except ImportError:
    cv2 = None

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.wmv', '.mpg', '.mpeg', '.flv', '.webm', '.3gp')


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
    Основний клас програми для сортування фотографій.
    Відображає фотографії та дозволяє користувачу переміщувати або копіювати їх
    до однієї з кількох цільових тек, зберігаючи ієрархію.
    Також підтримує вибір режиму сортування списку фотографій та попередній перегляд відео.
    """
    def __init__(self, master, source_dir, destination_dirs, transfer_mode="move", sort_mode="name"):
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
        self.video_preview_enabled = cv2 is not None

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
        self.current_video_capture = None
        self.current_video_path = None
        self.video_frame_job = None

        # Збираємо всі файли зображень з вихідної директорії та її підтек.
        self.photo_files = self._get_all_image_files()
        # Список впорядковується згідно з параметром sort_mode.
        self.current_photo_index = -1 # Індекс поточного фото, починаємо з -1, щоб перший виклик load_next_photo зробив його 0.

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

        print(f"Знайдено медіафайлів: {len(self.photo_files)}")
        print(f"Режим сортування: {self.sort_mode_label}")
        if not self.video_preview_enabled:
            print("Увага: модуль OpenCV не знайдено, попередній перегляд відео недоступний.")
        if len(self.photo_files) > 0:
            print("Перші 5 знайдених файлів:")
            for i, file in enumerate(list(self.photo_files)[:5]):
                print(f"  {i+1}. {file}")

    def _get_all_image_files(self):
        """
        Рекурсивно збирає всі файли зображень та відео з вихідної директорії
        та її підтек. Підтримувані розширення файлів.
        Після збирання застосовується обраний режим сортування.
        """
        image_extensions = IMAGE_EXTENSIONS
        video_extensions = VIDEO_EXTENSIONS
        all_extensions = image_extensions + video_extensions
        all_files = deque() # Використовуємо deque для ефективного додавання/видалення

        print(f"Пошук файлів із розширеннями: {all_extensions}")

        try:
            for root, dirs, files in os.walk(self.source_dir):
                print(f"Перевіряю теку: {root}")
                for file in files:
                    file_lower = file.lower()
                    if file_lower.endswith(image_extensions):
                        full_path = os.path.join(root, file)
                        all_files.append(full_path)
                        print(f"  Знайдено зображення: {file}")
                    elif file_lower.endswith(video_extensions):
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

    def _stop_video_preview(self):
        """
        Зупиняє поточний попередній перегляд відео, якщо він активний.
        """
        if self.video_frame_job is not None:
            try:
                self.master.after_cancel(self.video_frame_job)
            except Exception:
                pass
        self.video_frame_job = None

        if self.current_video_capture is not None:
            try:
                self.current_video_capture.release()
            except Exception:
                pass
        self.current_video_capture = None
        self.current_video_path = None

    def _start_video_preview(self, path, max_img_width, max_img_height):
        """
        Ініціалізує та запускає програвання відео у вікні.
        """
        if cv2 is None:
            return False

        try:
            capture = cv2.VideoCapture(path)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError("Не вдалося відкрити відеофайл.")

            self.current_video_capture = capture
            self.current_video_path = path
            self._display_next_video_frame(max_img_width, max_img_height)
            return True
        except Exception as exc:
            print(f"Попередження: неможливо відтворити відео {path}: {exc}")
            self._stop_video_preview()
            return False

    def _display_next_video_frame(self, max_img_width, max_img_height):
        """
        Зчитує наступний кадр відео та планує показ наступного.
        """
        if self.current_video_capture is None:
            return

        success, frame = self.current_video_capture.read()
        if not success or frame is None:
            # Спроба перезапустити відео з початку
            self.current_video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            success, frame = self.current_video_capture.read()
            if not success or frame is None:
                self._stop_video_preview()
                return

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        img.thumbnail((max_img_width, max_img_height), Image.LANCZOS)

        self.photo = ImageTk.PhotoImage(img)
        self.image_label.config(image=self.photo, text="")
        self.image_label.image = self.photo

        fps = self.current_video_capture.get(cv2.CAP_PROP_FPS)
        delay = 33
        if fps and fps > 0:
            delay = max(15, int(1000 / fps))

        if self.current_video_capture is None:
            return
        self.video_frame_job = self.master.after(delay, self._display_next_video_frame, max_img_width, max_img_height)

    def _is_video_file(self, path):
        """
        Перевіряє, чи належить файл до підтримуваних відеоформатів.
        """
        return path.lower().endswith(VIDEO_EXTENSIONS)

    def _load_media_preview(self, path):
        """
        Повертає PIL.Image з попереднім переглядом зображення або відео.
        """
        lower = path.lower()
        try:
            if lower.endswith(IMAGE_EXTENSIONS):
                with Image.open(path) as img:
                    return img.copy()
            if lower.endswith(VIDEO_EXTENSIONS):
                if not self.video_preview_enabled:
                    warning = "Встановіть opencv-python для попереднього перегляду."
                    print(f"Попередження: {warning}")
                    return self._create_placeholder_image("Відео", warning)
                return self._extract_video_frame(path)
            return self._create_placeholder_image("Непідтримуваний формат", os.path.basename(path))
        except Exception as exc:
            print(f"Попередження: не вдалося створити попередній перегляд для {path}: {exc}")
            return self._create_placeholder_image("Помилка попереднього перегляду", str(exc))

    def _extract_video_frame(self, path):
        """
        Зчитує перший кадр відео та повертає його як PIL.Image.
        """
        if cv2 is None:
            raise RuntimeError("Модуль OpenCV недоступний.")
        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("Не вдалося відкрити відеофайл.")

        success, frame = capture.read()
        capture.release()
        if not success or frame is None:
            raise RuntimeError("Не вдалося зчитати кадр відео.")

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)

    def _create_placeholder_image(self, title, subtitle=""):
        """
        Створює простий заглушковий кадр із текстом.
        """
        width, height = 800, 600
        img = Image.new("RGB", (width, height), color=(45, 45, 45))
        draw = ImageDraw.Draw(img)
        message = title if not subtitle else f"{title}\n{subtitle}"
        text_width, text_height = draw.multiline_textsize(message, spacing=8)
        position = ((width - text_width) / 2, (height - text_height) / 2)
        draw.multiline_text(position, message, fill=(255, 255, 255), align="center", spacing=8)
        return img

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
        Обробник подій зміни розміру вікна.
        Перезавантажує поточне фото, щоб воно адаптувалось до нового розміру вікна.
        """
        # Перевіряємо, чи це подія зміни розміру вікна, а не інша подія Configure.
        if event.widget == self.master and hasattr(self, 'current_photo_index'):
            # Перезавантажуємо поточне фото, щоб воно підлаштувалось під новий розмір.
            # Зменшуємо індекс на 1, щоб load_next_photo завантажила те ж саме фото.
            if self.current_photo_index >= 0:
                self.current_photo_index -= 1
                self.load_next_photo()

    def load_next_photo(self):
        """
        Завантажує та відображає наступний медіафайл зі списку.
        Адаптує розмір зображення до розміру вікна.
        """
        self._stop_video_preview()
        self.current_photo_index += 1
        if self.current_photo_index < len(self.photo_files):
            current_file_path = self.photo_files[self.current_photo_index]
            media_kind = "Відео" if self._is_video_file(current_file_path) else "Фото"
            instructions = (f"Натисніть {self.destination_instruction_text}, "
                            "'S' для пропуску, 'Q' для виходу.")
            self.status_label.config(
                text=(f"{media_kind}: {os.path.basename(current_file_path)} "
                      f"({self.current_photo_index + 1}/{len(self.photo_files)})\n"
                      f"{instructions}")
            )
            try:
                # Відкриття попереднього перегляду
                self.master.update_idletasks()

                # Отримуємо поточні розміри вікна для адаптації зображення
                window_width = self.master.winfo_width()
                window_height = self.master.winfo_height()

                # Якщо вікно ще не ініціалізовано, використовуємо значення за замовчуванням
                if window_width <= 1 or window_height <= 1:
                    window_width = 800
                    window_height = 600

                # Обчислюємо максимальний розмір для попереднього перегляду, залишаючи місце для статус-бару
                status_height = self.status_label.winfo_reqheight() if self.status_label.winfo_reqheight() > 0 else 60
                max_img_width = max(100, window_width - 40)  # Відступи, мінімум 100px
                max_img_height = max(100, window_height - status_height - 40)  # Відступи та висота статус-бару, мінімум 100px

                print(f"Розміри вікна: {window_width}x{window_height}, макс. розмір попереднього перегляду: {max_img_width}x{max_img_height}")

                played_video = False
                if media_kind == "Відео" and self.video_preview_enabled:
                    played_video = self._start_video_preview(current_file_path, max_img_width, max_img_height)

                if not played_video:
                    img = self._load_media_preview(current_file_path)
                    img.thumbnail((max_img_width, max_img_height), Image.LANCZOS)

                    self.photo = ImageTk.PhotoImage(img)
                    self.image_label.config(image=self.photo, text="")
                    # Зберігаємо посилання на зображення, щоб уникнути його збирання сміття
                    self.image_label.image = self.photo

                # Фокусуємо вікно для отримання подій клавіатури
                self.master.focus_force()

            except Exception as e:
                self.status_label.config(text=f"Помилка завантаження {os.path.basename(current_file_path)}: {e}\nПропускаю...")
                print(f"Помилка завантаження {current_file_path}: {e}")
                # Якщо виникла помилка, пропускаємо поточний файл і завантажуємо наступний.
                self.load_next_photo()
        else:
            # Якщо всі медіафайли відсортовано або немає підтримуваних файлів.
            if len(self.photo_files) == 0:
                supported_images = ", ".join(IMAGE_EXTENSIONS)
                supported_videos = ", ".join(VIDEO_EXTENSIONS)
                self.status_label.config(
                    text=("Не знайдено жодного медіафайлу у вказаній директорії!\n"
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
        key = event.char.upper() # Перетворюємо клавішу на верхній регістр для зручності
        if self.current_photo_index >= len(self.photo_files):
            return # Не обробляти, якщо всі медіафайли відсортовано

        current_file_path = self.photo_files[self.current_photo_index]

        if key in self.key_to_destination:
            self._move_photo(current_file_path, self.key_to_destination[key])
        elif key == 'S': # Пропустити фотографію
            self.status_label.config(text=f"Пропущено: {os.path.basename(current_file_path)}")
            self.master.update_idletasks() # Оновлюємо інтерфейс, щоб показати статус
        elif key == 'Q': # Вихід з програми
            self._stop_video_preview()
            self.master.destroy()
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
        destination_base_dir=/dest, то фото буде переміщено до /dest/a/b/c.jpg.
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
        print()
        print("Доступні режими сортування (--sort):")
        for key, label, _ in SORT_MODE_VARIANTS:
            print(f"  {key:15} - {label}")
        print("Підтримуються фото та відео; попередній перегляд відео потребує встановленого OpenCV.")
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
        print("  # Сортування за розміром (більші спочатку)")
        print("  python sort-photos.py --sort size-rev /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print()
        print("  # Windows приклад")
        print("  python sort-photos.py --mode copy --sort modified C:\\Photos C:\\Photos_Person1 C:\\Photos_Person2")

    args = sys.argv[1:]
    mode = "move"
    sort_mode_key = "name"
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
    app = PhotoSorterApp(root, source_directory, destination_directories, transfer_mode=mode, sort_mode=sort_mode_key)
    # Запускаємо головний цикл подій Tkinter.
    root.mainloop()
