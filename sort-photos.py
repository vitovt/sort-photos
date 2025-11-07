#!/usr/bin/env python3

import os
import shutil
from tkinter import Tk, Label, PhotoImage
from PIL import Image, ImageTk
from collections import deque
import sys

class PhotoSorterApp:
    """
    Основний клас програми для сортування фотографій.
    Відображає фотографії та дозволяє користувачу переміщувати або копіювати їх
    до однієї з кількох цільових тек, зберігаючи ієрархію.
    """
    def __init__(self, master, source_dir, destination_dirs, transfer_mode="move"):
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

        # Збираємо всі файли зображень з вихідної директорії та її підтек.
        self.photo_files = self._get_all_image_files()
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

        print(f"Знайдено файлів зображень: {len(self.photo_files)}")
        if len(self.photo_files) > 0:
            print("Перші 5 знайдених файлів:")
            for i, file in enumerate(list(self.photo_files)[:5]):
                print(f"  {i+1}. {file}")

    def _get_all_image_files(self):
        """
        Рекурсивно збирає всі файли зображень з вихідної директорії
        та її підтек. Підтримувані розширення файлів.
        """
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
        all_files = deque() # Використовуємо deque для ефективного додавання/видалення

        print(f"Пошук файлів із розширеннями: {image_extensions}")

        try:
            for root, dirs, files in os.walk(self.source_dir):
                print(f"Перевіряю теку: {root}")
                for file in files:
                    file_lower = file.lower()
                    if file_lower.endswith(image_extensions):
                        full_path = os.path.join(root, file)
                        all_files.append(full_path)
                        print(f"  Знайдено: {file}")
                    else:
                        print(f"  Пропущено: {file} (не підтримується)")
        except Exception as e:
            print(f"Помилка під час пошуку файлів: {e}")

        return all_files

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
        Завантажує та відображає наступне фото зі списку.
        Адаптує розмір зображення до розміру вікна.
        """
        self.current_photo_index += 1
        if self.current_photo_index < len(self.photo_files):
            current_file_path = self.photo_files[self.current_photo_index]
            instructions = (f"Натисніть {self.destination_instruction_text}, "
                            "'S' для пропуску, 'Q' для виходу.")
            self.status_label.config(
                text=(f"Файл: {os.path.basename(current_file_path)} "
                      f"({self.current_photo_index + 1}/{len(self.photo_files)})\n"
                      f"{instructions}")
            )
            try:
                # Відкриття зображення
                img = Image.open(current_file_path)

                # Оновлюємо вікно, щоб отримати правильні розміри
                self.master.update_idletasks()

                # Отримуємо поточні розміри вікна для адаптації зображення
                window_width = self.master.winfo_width()
                window_height = self.master.winfo_height()

                # Якщо вікно ще не ініціалізовано, використовуємо значення за замовчуванням
                if window_width <= 1 or window_height <= 1:
                    window_width = 800
                    window_height = 600

                # Обчислюємо максимальний розмір для зображення, залишаючи місце для статус-бару
                status_height = self.status_label.winfo_reqheight() if self.status_label.winfo_reqheight() > 0 else 60
                max_img_width = max(100, window_width - 40)  # Відступи, мінімум 100px
                max_img_height = max(100, window_height - status_height - 40)  # Відступи та висота статус-бару, мінімум 100px

                print(f"Розміри вікна: {window_width}x{window_height}, макс. розмір зображення: {max_img_width}x{max_img_height}")

                # Змінюємо розмір зображення, зберігаючи пропорції
                img.thumbnail((max_img_width, max_img_height), Image.LANCZOS)

                self.photo = ImageTk.PhotoImage(img)
                self.image_label.config(image=self.photo)
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
            # Якщо всі фотографії відсортовано або немає фотографій.
            if len(self.photo_files) == 0:
                self.status_label.config(text="Не знайдено жодного файлу зображення у вказаній директорії!\n"
                                            "Перевірте шлях та наявність файлів із розширеннями:\n"
                                            ".png, .jpg, .jpeg, .gif, .bmp, .tiff, .webp")
                self.image_label.config(text="Файли не знайдено", image="")
            else:
                self.status_label.config(text="Усі фотографії відсортовано! Завершення.")
                # Закриваємо вікно через 3 секунди.
                self.master.after(3000, self.master.destroy)

    def on_key_press(self, event):
        """
        Обробник натискання клавіш.
        Визначає дію залежно від натиснутої клавіші.
        """
        key = event.char.upper() # Перетворюємо клавішу на верхній регістр для зручності
        if self.current_photo_index >= len(self.photo_files):
            return # Не обробляти, якщо всі фото відсортовано

        current_file_path = self.photo_files[self.current_photo_index]

        if key in self.key_to_destination:
            self._move_photo(current_file_path, self.key_to_destination[key])
        elif key == 'S': # Пропустити фотографію
            self.status_label.config(text=f"Пропущено: {os.path.basename(current_file_path)}")
            self.master.update_idletasks() # Оновлюємо інтерфейс, щоб показати статус
        elif key == 'Q': # Вихід з програми
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
        Переміщує або копіює фотографію з 'source_path' до 'destination_base_dir',
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
        print("Використання: python sort-photos.py [--mode move|copy] <вихідна_тека> <тека_1> <тека_2> [тека_3 ...]")
        print("Приклад: python sort-photos.py --mode move /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print("Приклад (багато тек): python sort-photos.py /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша /home/user/Фото_Родина")
        print("Приклад (Windows): python sort-photos.py --mode copy C:\\Photos C:\\Photos_Person1 C:\\Photos_Person2")

    args = sys.argv[1:]
    mode = "move"
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
    app = PhotoSorterApp(root, source_directory, destination_directories, transfer_mode=mode)
    # Запускаємо головний цикл подій Tkinter.
    root.mainloop()
