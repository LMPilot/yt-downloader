# YT Downloader

Проста програма для завантаження відео з YouTube (одне відео, плейлист або цілий канал) на основі [yt-dlp](https://github.com/yt-dlp/yt-dlp) з інтерфейсом на [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter).

Кожне відео зберігається в **окрему папку**, названу за назвою відео:

```
Downloads/YT/
├── Назва першого відео/
│   ├── Назва першого відео.mp4
│   └── info.txt
└── Назва другого відео/
    ├── Назва другого відео.mp4
    └── info.txt
```

`info.txt` (UTF-8): **1-й рядок** — назва відео, **рядки 2–4** — порожні, **з 5-го рядка** — повний опис.

## Можливості

- Посилання на відео, плейлист або канал (`https://www.youtube.com/@назва` — вкладка «Відео» підставляється автоматично).
- Режими: **Одне відео**, **N відео з каналу** (останні N), **Усі відео з каналу**.
- Якість: Найкраща, 2160p, 1440p, 1080p, 720p, 480p, 360p (якщо потрібної немає — береться найближча), результат у MP4.
- **Лише аудіо (MP3)** з бітрейтом 320 / 192 / 128 кбіт/с.
- Галочка «Зберігати назву та опис» (`info.txt`).
- Вибір папки (за замовчуванням `~/Downloads/YT`).
- Прогрес (відео k/N, відсотки, швидкість), журнал, кнопка «Скасувати».
- Помилка на одному відео не зупиняє завантаження каналу.
- Якщо відео вже завантажене — повторно не качається.

## Встановлення (Windows 10/11)

1. Встановіть **Python 3.10+** з [python.org](https://www.python.org/downloads/) (під час встановлення поставте галочку **Add Python to PATH**).
2. Встановіть **FFmpeg** (потрібен для MP4 та MP3) і **Deno** (потрібен yt-dlp, щоб YouTube віддавав усі формати). У PowerShell:

   ```powershell
   winget install Gyan.FFmpeg
   winget install DenoLand.Deno
   ```

   Після встановлення **закрийте й знову відкрийте** PowerShell (щоб оновився PATH).
   Замість встановлення FFmpeg можна просто покласти `ffmpeg.exe` у папку з програмою.
3. Завантажте цей репозиторій (кнопка **Code → Download ZIP** або `git clone`) і в його папці виконайте:

   ```powershell
   pip install -r requirements.txt
   ```

## Запуск

```powershell
python app.py
```

Вставте посилання, оберіть режим і якість, натисніть **Завантажити**.

### Оновлення yt-dlp

YouTube часто змінюється, тож якщо завантаження раптом перестали працювати — оновіть yt-dlp:

```powershell
pip install -U "yt-dlp[default]"
```

## Збірка в один .exe (необовʼязково)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name YT-Downloader --collect-all customtkinter --collect-all yt_dlp_ejs app.py
```

Готовий файл: `dist\YT-Downloader.exe`. FFmpeg і Deno в .exe не входять — їх потрібно встановити (див. вище) або покласти `ffmpeg.exe` поруч із `YT-Downloader.exe`.

## Тести

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

## Структура

- `downloader.py` — логіка завантаження (без GUI): налаштування yt-dlp, назви папок, `info.txt`.
- `app.py` — графічний інтерфейс на CustomTkinter.
- `tests/` — юніт-тести.

Програма призначена для особистого використання. Завантажуйте лише той контент, на який маєте право.
