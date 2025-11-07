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
    Відображає фотографії та дозволяє користувачу переміщувати їх
    до однієї з двох цільових тек, зберігаючи ієрархію.
    """
    def __init__(self, master, source_dir, dest_dir_person1, dest_dir_person2):
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
        self.dest_dir_person1 = os.path.abspath(dest_dir_person1)
        self.dest_dir_person2 = os.path.abspath(dest_dir_person2)

        # Створення цільових директорій, якщо вони не існують.
        # exist_ok=True запобігає помилці, якщо тека вже є.
        os.makedirs(self.dest_dir_person1, exist_ok=True)
        os.makedirs(self.dest_dir_person2, exist_ok=True)

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
            self.status_label.config(text=f"Файл: {os.path.basename(current_file_path)} ({self.current_photo_index + 1}/{len(self.photo_files)})\n"
                                          "Натисніть '1' для Людина1, '2' для Людина2, 'S' для пропуску, 'Q' для виходу.")
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

        if key == '1':
            self._move_photo(current_file_path, self.dest_dir_person1)
        elif key == '2':
            self._move_photo(current_file_path, self.dest_dir_person2)
        elif key == 'S': # Пропустити фотографію
            self.status_label.config(text=f"Пропущено: {os.path.basename(current_file_path)}")
            self.master.update_idletasks() # Оновлюємо інтерфейс, щоб показати статус
        elif key == 'Q': # Вихід з програми
            self.master.destroy()
            return
        else:
            self.status_label.config(text="Невідома клавіша. Використовуйте '1', '2', 'S' або 'Q'.")
            return # Не завантажуємо наступне фото, якщо була неправильна клавіша

        # Завантажуємо наступне фото після успішної обробки (переміщення або пропуску).
        self.load_next_photo()

    def _move_photo(self, source_path, destination_base_dir):
        """
        Переміщує фотографію з 'source_path' до 'destination_base_dir',
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
            # Переміщуємо файл.
            shutil.move(source_path, destination_path)
            self.status_label.config(text=f"Переміщено: {os.path.basename(source_path)} до {os.path.basename(destination_base_dir)}")
            print(f"Переміщено: {source_path} -> {destination_path}")
        except Exception as e:
            # Обробка помилок під час переміщення файлу.
            self.status_label.config(text=f"Помилка переміщення {os.path.basename(source_path)}: {e}")
            print(f"Помилка переміщення {source_path}: {e}")

if __name__ == "__main__":
    # Перевіряємо правильність кількості аргументів командного рядка.
    if len(sys.argv) != 4:
        print("Використання: python sort-photos.py <вихідна_тека> <тека_для_Людини1> <тека_для_Людини2>")
        print("Приклад: python sort-photos.py /home/user/ВсіФото /home/user/Фото_Вася /home/user/Фото_Маша")
        print("Приклад (Windows): python sort-photos.py C:\\Photos C:\\Photos_Person1 C:\\Photos_Person2")
        sys.exit(1)

    # Отримуємо шляхи з аргументів командного рядка.
    source_directory = sys.argv[1]
    person1_directory = sys.argv[2]
    person2_directory = sys.argv[3]

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
    app = PhotoSorterApp(root, source_directory, person1_directory, person2_directory)
    # Запускаємо головний цикл подій Tkinter.
    root.mainloop()
