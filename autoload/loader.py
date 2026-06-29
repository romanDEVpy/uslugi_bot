"""
Основной модуль загрузчика: авторизация → загрузка двух страниц → объединение.
Также используется как шаблонный движок для подмены данных.
"""

import os
import re
import asyncio
import logging
import random
import shutil
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import aiohttp

logger = logging.getLogger(__name__)

# ─── Константы ───────────────────────────────────────────────────────────────

LOGIN_URL = "https://www.gosuslugi.ru/"

PAGES = [
    {
        "url": "https://lk.gosuslugi.ru/profile/personal",
        "local_name": "profile/personal.html",
    },
    {
        "url": "https://lk.gosuslugi.ru/profile/personal/id-doc",
        "local_name": "profile/personal/id-doc.html",
    },
]

# Домены, ассеты с которых можно скачивать
ALLOWED_DOMAINS = ["gosuslugi.ru", "gu-st.ru", "lk.gosuslugi.ru"]

# Паттерны скриптов, которые нужно удалить при очистке
BAD_SCRIPTS = [
    "polyfills", "main.", "remoteEntry", "health",
    "yandex.ru", "metrika", "tag.js", "DOMContentLoaded",
    "new-lk", "check-session", "mc.yandex",
    "widget-minimax", "boot-minimax", "usefulBanners", "load_timing",
    "authProviderUrl",
]

# Домены, URL которых нужно переписать на относительные
REWRITE_DOMAINS = [
    "https://gu-st.ru", "http://gu-st.ru",
    "https://www.gosuslugi.ru", "http://www.gosuslugi.ru",
    "https://lk.gosuslugi.ru", "http://lk.gosuslugi.ru",
]

# Расширения, которые не скачиваем
SKIPPED_EXTENSIONS = {
    '.mp4', '.mp3', '.avi', '.mov', '.ogg', '.wav', '.flac', '.webm', '.mkv',
    '.zip', '.tar', '.gz', '.pdf', '.rar', '.7z', '.exe', '.dmg', '.pkg',
    '.epub', '.mobi', '.apk', '.ipa', '.docx', '.xlsx', '.pptx',
    '.psd', '.ai', '.sketch', '.torrent', '.iso', '.bin',
}

# Селектор лоадера (его исчезновения ждём)
LOADER_SELECTOR = ".container-app-loader"

# Время дополнительного ожидания рендеринга (сек.)
EXTRA_WAIT = 8.0

CSS_URL_REGEX = re.compile(r'url\(\s*[\'\"]?([^\'\"\)\s]+)[\'\"]?\s*\)')


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def should_skip_url(url: str) -> bool:
    """Проверяет, нужно ли пропустить URL."""
    if not url:
        return True
    url = url.strip()
    if url.startswith(('javascript:', 'mailto:', 'tel:', 'data:', 'sms:', '#')):
        return True
    parsed = urlparse(url)
    path = parsed.path.lower()
    _, ext = os.path.splitext(path)
    if ext in SKIPPED_EXTENSIONS:
        return True
    if parsed.scheme and parsed.scheme not in ('http', 'https'):
        return True
    return False


def is_allowed_domain(url: str) -> bool:
    """Проверяет, относится ли URL к разрешённым доменам."""
    if not url:
        return False
    url = url.strip()
    if url.startswith('//'):
        url = f"https:{url}"
    parsed = urlparse(url)
    if not parsed.netloc:
        return True
    netloc = parsed.netloc.lower()
    for domain in ALLOWED_DOMAINS:
        domain = domain.lower().strip()
        if netloc == domain or netloc.endswith("." + domain):
            return True
    return False


def sanitize_filename(name: str) -> str:
    """Удаляет запрещённые символы из имени файла."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    sanitized = sanitized.strip('.')
    return sanitized if sanitized else '_'


def url_to_local_path(url: str, base_url: str) -> str:
    """Преобразует URL в локальный путь для сохранения."""
    absolute_url = urljoin(base_url, url)
    parsed = urlparse(absolute_url)

    # Для ассетов с других доменов — добавляем домен в путь
    base_parsed = urlparse(base_url)
    if parsed.netloc and parsed.netloc.lower() != base_parsed.netloc.lower():
        domain_prefix = sanitize_filename(parsed.netloc)
        path = parsed.path
        if not path or path == '/':
            path = '/index.html'
        segments = [domain_prefix] + [seg for seg in path.split('/') if seg]
    else:
        path = parsed.path
        if not path or path == '/':
            path = '/index.html'
        segments = [seg for seg in path.split('/') if seg]

    ends_with_slash = path.endswith('/')

    if ends_with_slash:
        filename = 'index.html'
        dir_segments = segments
    else:
        if segments:
            filename = segments[-1]
            dir_segments = segments[:-1]
        else:
            filename = 'index.html'
            dir_segments = []

    _, ext = os.path.splitext(filename)
    if not ext:
        filename = filename + '.html' if not ends_with_slash else 'index.html'

    # Query-параметры для уникальности
    if parsed.query:
        from urllib.parse import parse_qsl
        query_params = parse_qsl(parsed.query)
        if query_params:
            query_str = '_'.join(
                f"{sanitize_filename(k)}_{sanitize_filename(v)}" for k, v in query_params
            )
            if len(query_str) > 100:
                query_str = query_str[:100] + '_etc'
            base_name, file_ext = os.path.splitext(filename)
            filename = f"{base_name}_{query_str}{file_ext}"

    clean_dir = [sanitize_filename(seg) for seg in dir_segments]
    clean_filename = sanitize_filename(filename)

    if clean_dir:
        local_path = os.path.join(*clean_dir, clean_filename)
    else:
        local_path = clean_filename

    return local_path.replace('\\', '/')


def get_relative_path(current_local_path: str, target_local_path: str) -> str:
    """Вычисляет относительный путь от одного файла к другому."""
    current_dir = os.path.dirname(current_local_path)
    rel_path = os.path.relpath(target_local_path, start=current_dir)
    return rel_path.replace('\\', '/')


def to_relative(url: str, rel_root: str) -> str:
    """Преобразует абсолютный URL в относительный путь."""
    if not url:
        return url
    url = url.strip()
    if url.startswith(('data:', '#', 'javascript:', 'mailto:', 'tel:')):
        return url

    for prefix in REWRITE_DOMAINS:
        for scheme_prefix in (prefix, prefix.replace('https:', 'http:'), prefix.replace('https:', '')):
            if url.startswith(scheme_prefix):
                url = url[len(scheme_prefix):]
                break

    # Protocol-relative
    for domain in ALLOWED_DOMAINS:
        for pfx in (f'//{domain}', f'//www.{domain}'):
            if url.startswith(pfx):
                url = url[len(pfx):]
                break

    if url.startswith('/'):
        url = url.lstrip('/')
        return rel_root + url

    return url


# ─── Основной класс ─────────────────────────────────────────────────────────

class GosuslugiLoader:
    """
    Полностью автономный загрузчик:
    авторизация → скачивание страниц + ассетов → очистка → сборка.
    """

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = os.path.abspath(output_dir)
        self.downloaded_assets = set()
        self.aiohttp_session = None
        self.cookies_str = ""
        self.custom_fio = ""          # Пользовательское ФИО (ФАМИЛИЯ ИМЯ ОТЧЕСТВО)
        self.custom_birth_date = ""   # Пользовательская дата рождения
        self.custom_gender = ""       # Пользовательский пол
        self.custom_passport = ""     # Рандомно сгенерированная серия/номер
        self.custom_issue_date = ""   # Дата выдачи паспорта (рождение + 14 лет + n дней)
        self.custom_inn = ""          # Рандомно сгенерированный ИНН (12 цифр)
        self.custom_snils = ""         # Рандомно сгенерированный СНИЛС (XXX-XXX-XXX YY)
        self.user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )

    async def run(self):
        """Главная точка входа: полный пайплайн."""
        logger.info("Запуск полного пайплайна загрузки...")
        os.makedirs(self.output_dir, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()

            # ── Шаг 1: Авторизация ──
            await self._do_auth(page, context)

            # ── Шаг 1.5: Ввод пользовательских данных ──
            self._prompt_custom_data()

            # ── Шаг 2: Загрузка страниц и ассетов ──
            await self._init_aiohttp_session()

            for page_info in PAGES:
                await self._fetch_and_save_page(page, page_info["url"], page_info["local_name"])
                await asyncio.sleep(1.5)

            await self._close_aiohttp_session()
            await browser.close()

        # ── Шаг 3: Очистка HTML ──
        self._clean_all()

        # ── Шаг 4: Генерация и инъекция offline.js ──
        self._assemble()

        # ── Шаг 5: Подмена персональных данных ──
        self._apply_custom_data()

        logger.info("")
        logger.info("=" * 70)
        logger.info("  ГОТОВО! Офлайн-сайт сохранён в: %s", self.output_dir)
        logger.info("=" * 70)

    # ─── Авторизация ─────────────────────────────────────────────────────

    async def _do_auth(self, page, context):
        """Открывает госуслуги для ручного входа, ждёт Enter."""
        logger.info("Открываю страницу для авторизации: %s", LOGIN_URL)
        await page.goto(LOGIN_URL)

        logger.info("")
        logger.info("=" * 60)
        logger.info("  Войдите в аккаунт в открывшемся окне браузера.")
        logger.info("  После успешного входа вернитесь в консоль")
        logger.info("  и нажмите [Enter]...")
        logger.info("=" * 60)
        logger.info("")

        await asyncio.to_thread(input, ">>> Нажмите [Enter] после авторизации... ")

        # Извлекаем куки после ручного входа
        auth_cookies = await context.cookies()
        cookie_pairs = [f"{c['name']}={c['value']}" for c in auth_cookies]
        self.cookies_str = "; ".join(cookie_pairs)
        logger.info("Куки авторизации получены (%d шт.)", len(auth_cookies))

    # ─── Ввод пользовательских данных и генерация паспорта ────────────────

    @staticmethod
    def _generate_passport_number() -> str:
        """
        Генерирует случайную серию и номер паспорта в формате 'XXXX XXXXXX'.
        Серия: 4 цифры, Номер: 6 цифр.
        """
        series = random.randint(1000, 9999)
        number = random.randint(100000, 999999)
        return f"{series} {number:06d}"

    @staticmethod
    def _generate_issue_date(birth_date_str: str) -> str:
        """
        Генерирует дату выдачи паспорта: дата рождения + 14 лет + random(1, 60) дней.
        """
        birth = datetime.strptime(birth_date_str, "%d.%m.%Y")
        try:
            at_14 = birth.replace(year=birth.year + 14)
        except ValueError:
            # 29 февраля → 28 февраля
            at_14 = birth.replace(year=birth.year + 14, day=28)
        issue = at_14 + timedelta(days=random.randint(1, 60))
        return issue.strftime("%d.%m.%Y")

    @staticmethod
    def _generate_inn() -> str:
        """
        Генерирует валидный 12-значный ИНН для физического лица.
        """
        region = f"{random.randint(1, 99):02d}"
        tax_office = f"{random.randint(1, 99):02d}"
        record = f"{random.randint(100000, 999999):06d}"
        digits = [int(d) for d in (region + tax_office + record)]
        
        # 11-й контрольный разряд
        weights11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        val11 = sum(d * w for d, w in zip(digits, weights11)) % 11
        d11 = 0 if val11 == 10 else val11
        digits.append(d11)
        
        # 12-й контрольный разряд
        weights12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        val12 = sum(d * w for d, w in zip(digits, weights12)) % 11
        d12 = 0 if val12 == 10 else val12
        digits.append(d12)
        
        return "".join(str(d) for d in digits)

    @staticmethod
    def _generate_snils() -> str:
        """
        Генерирует валидный СНИЛС в формате 'XXX-XXX-XXX YY'.
        """
        d1 = random.randint(0, 9)
        d2 = random.randint(0, 9)
        d3 = random.randint(0, 9)
        if d1 == 0 and d2 == 0 and d3 == 0:
            d3 = 1
        
        digits = [d1, d2, d3] + [random.randint(0, 9) for _ in range(6)]
        
        s = 0
        for i in range(9):
            s += digits[i] * (9 - i)
        
        if s < 100:
            checksum = s
        elif s == 100 or s == 101:
            checksum = 0
        else:
            rem = s % 101
            if rem == 100 or rem == 101:
                checksum = 0
            else:
                checksum = rem
                
        snils_str = "".join(str(d) for d in digits)
        return f"{snils_str[:3]}-{snils_str[3:6]}-{snils_str[6:9]} {checksum:02d}"

    def _prompt_custom_data(self):
        """
        Запрашивает у пользователя дату рождения и генерирует рандомный номер паспорта.
        Вызывается ПЕРЕД загрузкой страниц (пока браузер работает в фоне).
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info("  НАСТРОЙКА ПЕРСОНАЛЬНЫХ ДАННЫХ")
        logger.info("=" * 60)

        # Запрос даты рождения
        while True:
            birth_date = input(">>> Введите дату рождения (ДД.ММ.ГГГГ): ").strip()
            if re.match(r'^\d{2}\.\d{2}\.\d{4}$', birth_date):
                self.custom_birth_date = birth_date
                break
            else:
                print("    Неверный формат! Используйте ДД.ММ.ГГГГ (например: 15.03.2005)")

        # Генерация паспорта, даты выдачи, ИНН и СНИЛС
        self.custom_passport = self._generate_passport_number()
        self.custom_issue_date = self._generate_issue_date(self.custom_birth_date)
        self.custom_inn = self._generate_inn()
        self.custom_snils = self._generate_snils()

        logger.info("")
        logger.info("  Дата рождения: %s", self.custom_birth_date)
        logger.info("  Паспорт (сгенерирован): %s", self.custom_passport)
        logger.info("  Дата выдачи (сгенерирована): %s", self.custom_issue_date)
        logger.info("  ИНН (сгенерирован): %s", self.custom_inn)
        logger.info("  СНИЛС (сгенерирован): %s", self.custom_snils)
        logger.info("")

    def _apply_custom_data(self):
        """
        Подменяет ФИО, дату рождения, серию/номер паспорта и дату выдачи
        в загруженных HTML-файлах.
        
        Элементы для замены:
        1. ФИО (id-doc.html):
           <p class="title-h4">МЕДВЕДЕВ РОМАН КОНСТАНТИНОВИЧ</p>  ← заменяется
        
        2. Дата рождения (id-doc.html):
           <div class="text-plain gray">Дата рождения</div>
           <div class="text-plain mt-4">25.02.2008</div>  ← заменяется
        
        3. Серия/номер паспорта (personal.html):
           <p class="title-h5">4625 039329</p>  ← заменяется
        
        4. Серия/номер паспорта (id-doc.html):
           <div class="text-help">Серия и номер паспорта</div>
           <p class="title-h4 mt-4">4625 039329</p>  ← заменяется

        5. Дата выдачи (personal.html, id-doc.html):
           <div class="text-plain gray">Дата выдачи</div>
           <div class="text-plain mt-4">15.05.2025</div>  ← заменяется
        """
        if not self.custom_birth_date and not self.custom_passport and not self.custom_fio and not self.custom_gender and not self.custom_inn and not self.custom_snils:
            return

        logger.info("Подмена персональных данных в HTML-файлах...")

        # Регулярное выражение для серии/номера паспорта: "XXXX XXXXXX"
        passport_regex = re.compile(r'\b\d{4}\s\d{6}\b')

        for page_info in PAGES:
            filepath = os.path.join(self.output_dir, page_info["local_name"])
            if not os.path.exists(filepath):
                logger.warning("Файл не найден для подмены: %s", filepath)
                continue

            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                html = f.read()

            soup = BeautifulSoup(html, 'lxml')
            changes_made = 0

            # ── Замена ФИО ──
            if self.custom_fio:
                # ФИО в id-doc.html: <p class="title-h4"> внутри div.user-info
                for user_info_div in soup.find_all('div', class_='user-info'):
                    fio_tag = user_info_div.find('p', class_='title-h4')
                    if fio_tag:
                        old_fio = fio_tag.get_text(strip=True)
                        fio_tag.string = self.custom_fio
                        logger.info("  [%s] ФИО: %s → %s",
                                    page_info['local_name'], old_fio, self.custom_fio)
                        changes_made += 1

                # ── Замена инициалов аватара ──
                fio_parts = [p for p in self.custom_fio.split() if p]
                if fio_parts:
                    if len(fio_parts) >= 2:
                        initials = fio_parts[0][0] + fio_parts[1][0]
                    else:
                        initials = fio_parts[0][0]
                    initials = initials.upper()
                    for avatar_div in soup.find_all('div', class_='no-avatar'):
                        old_initials = avatar_div.get_text(strip=True)
                        avatar_div.string = initials
                        logger.info("  [%s] Инициалы аватара: %s → %s",
                                    page_info['local_name'], old_initials, initials)
                        changes_made += 1

            # ── Замена даты рождения ──
            if self.custom_birth_date:
                # Ищем все элементы с текстом "Дата рождения"
                for label_div in soup.find_all(string=re.compile(r'Дата рождения')):
                    label_el = label_div.parent
                    if not label_el:
                        continue
                    # Ищем соседний div с датой (следующий сиблинг)
                    container = label_el.parent
                    if not container:
                        continue
                    # Находим div.text-plain.mt-4 внутри того же контейнера
                    value_div = container.find(
                        lambda tag: tag.name in ('div', 'p')
                        and 'text-plain' in tag.get('class', [])
                        and 'mt-4' in tag.get('class', [])
                    )
                    if value_div and re.match(r'\d{2}\.\d{2}\.\d{4}', value_div.get_text(strip=True)):
                        old_date = value_div.get_text(strip=True)
                        value_div.string = self.custom_birth_date
                        logger.info("  [%s] Дата рождения: %s → %s",
                                    page_info['local_name'], old_date, self.custom_birth_date)
                        changes_made += 1

            # ── Замена пола ──
            if self.custom_gender:
                for label_div in soup.find_all(string=re.compile(r'^\s*Пол\s*$')):
                    label_el = label_div.parent
                    if not label_el:
                        continue
                    container = label_el.parent
                    if not container:
                        continue
                    value_div = container.find(
                        lambda tag: tag.name in ('div', 'p')
                        and 'text-plain' in tag.get('class', [])
                        and 'mt-4' in tag.get('class', [])
                    )
                    if value_div:
                        old_gender = value_div.get_text(strip=True)
                        value_div.string = self.custom_gender
                        logger.info("  [%s] Пол: %s → %s",
                                    page_info['local_name'], old_gender, self.custom_gender)
                        changes_made += 1

            # ── Замена серии/номера паспорта ──
            if self.custom_passport:
                # Способ 1: <p class="title-h5"> с паспортом (personal.html)
                for p_tag in soup.find_all('p', class_='title-h5'):
                    text = p_tag.get_text(strip=True)
                    if passport_regex.match(text):
                        old_passport = text
                        p_tag.string = self.custom_passport
                        logger.info("  [%s] Паспорт (title-h5): %s → %s",
                                    page_info['local_name'], old_passport, self.custom_passport)
                        changes_made += 1

                # Способ 2: <p class="title-h4 mt-4"> после "Серия и номер паспорта"
                for label_div in soup.find_all(string=re.compile(r'Серия и номер паспорта')):
                    label_el = label_div.parent
                    if not label_el:
                        continue
                    container = label_el.parent
                    if not container:
                        continue
                    value_p = container.find(
                        lambda tag: tag.name == 'p'
                        and 'title-h4' in tag.get('class', [])
                    )
                    if value_p and passport_regex.match(value_p.get_text(strip=True)):
                        old_passport = value_p.get_text(strip=True)
                        value_p.string = self.custom_passport
                        logger.info("  [%s] Паспорт (title-h4): %s → %s",
                                    page_info['local_name'], old_passport, self.custom_passport)
                        changes_made += 1

            # ── Замена даты выдачи ──
            if self.custom_issue_date:
                for label_div in soup.find_all(string=re.compile(r'Дата выдачи')):
                    label_el = label_div.parent
                    if not label_el:
                        continue
                    container = label_el.parent
                    if not container:
                        continue
                    value_div = container.find(
                        lambda tag: tag.name in ('div', 'p')
                        and 'text-plain' in tag.get('class', [])
                        and 'mt-4' in tag.get('class', [])
                    )
                    if value_div and re.match(r'\d{2}\.\d{2}\.\d{4}', value_div.get_text(strip=True)):
                        old_date = value_div.get_text(strip=True)
                        value_div.string = self.custom_issue_date
                        logger.info("  [%s] Дата выдачи: %s → %s",
                                    page_info['local_name'], old_date, self.custom_issue_date)
                        changes_made += 1

            # ── Замена СНИЛС ──
            if self.custom_snils:
                for snils_card in soup.find_all('lk-snils-card'):
                    p_tag = snils_card.find('p', class_='title-h5')
                    if p_tag:
                        old_snils = p_tag.get_text(strip=True)
                        p_tag.string = self.custom_snils
                        logger.info("  [%s] СНИЛС: %s → %s",
                                    page_info['local_name'], old_snils, self.custom_snils)
                        changes_made += 1

            # ── Замена ИНН ──
            if self.custom_inn:
                for inn_card in soup.find_all('lk-inn-card'):
                    p_tag = inn_card.find('p', class_='title-h5')
                    if p_tag:
                        old_inn = p_tag.get_text(strip=True)
                        p_tag.string = self.custom_inn
                        logger.info("  [%s] ИНН: %s → %s",
                                    page_info['local_name'], old_inn, self.custom_inn)
                        changes_made += 1

            # Сохраняем если были изменения
            if changes_made > 0:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(str(soup))
                logger.info("  Сохранено %d изменений в %s", changes_made, page_info['local_name'])

        logger.info("Подмена персональных данных завершена.")

    # ─── aiohttp сессия для скачивания ассетов ───────────────────────────

    async def _init_aiohttp_session(self):
        """Инициализирует aiohttp-сессию с куками."""
        cookies = {}
        if self.cookies_str:
            for pair in self.cookies_str.split(';'):
                pair = pair.strip()
                if '=' in pair:
                    name, value = pair.split('=', 1)
                    cookies[name.strip()] = value.strip()

        self.aiohttp_session = aiohttp.ClientSession(
            cookies=cookies,
            headers={"User-Agent": self.user_agent},
            timeout=aiohttp.ClientTimeout(total=20)
        )

    async def _close_aiohttp_session(self):
        if self.aiohttp_session:
            await self.aiohttp_session.close()
            self.aiohttp_session = None

    # ─── Скачивание одной страницы ───────────────────────────────────────

    async def _fetch_and_save_page(self, page, url: str, local_name: str):
        """Загружает страницу, скачивает ассеты, сохраняет HTML."""
        logger.info("Загрузка страницы: %s", url)

        try:
            response = await page.goto(url, timeout=30000, wait_until="load")

            # Ждём скрытия лоадера
            try:
                await page.wait_for_selector(LOADER_SELECTOR, state="hidden", timeout=15000)
            except Exception:
                pass

            # Ждём networkidle
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # Дополнительное ожидание рендеринга
            if EXTRA_WAIT > 0:
                await page.wait_for_timeout(EXTRA_WAIT * 1000)

            actual_url = page.url
            status_code = response.status if response else 200

            if status_code >= 400:
                logger.warning("Ошибка %d для %s", status_code, url)
                return

            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'lxml')

            # Скачиваем и перезаписываем ассеты
            await self._process_page_assets(soup, actual_url, local_name)

            # Перезаписываем ссылки <a>
            for a_tag in soup.find_all('a', href=True):
                raw_href = a_tag['href'].strip()
                if should_skip_url(raw_href):
                    continue
                abs_link = urljoin(actual_url, raw_href)
                if is_allowed_domain(abs_link):
                    abs_link_no_frag = abs_link.split('#')[0]
                    fragment = abs_link.split('#')[1] if '#' in abs_link else ''
                    target_local = url_to_local_path(abs_link_no_frag, LOGIN_URL)

                    if abs_link_no_frag == actual_url:
                        rel_link = f"#{fragment}" if fragment else "#"
                    else:
                        rel_link = get_relative_path(local_name, target_local)
                        if fragment:
                            rel_link = f"{rel_link}#{fragment}"
                    a_tag['href'] = rel_link

            # Сохранение файла
            full_filepath = os.path.join(self.output_dir, local_name)
            os.makedirs(os.path.dirname(full_filepath), exist_ok=True)

            with open(full_filepath, 'w', encoding='utf-8') as f:
                f.write(str(soup))

            logger.info("Сохранена страница: %s", local_name)

        except Exception as e:
            logger.error("Не удалось обработать %s: %s", url, e, exc_info=True)

    # ─── Обработка ассетов на странице ───────────────────────────────────

    async def _process_page_assets(self, soup: BeautifulSoup, actual_url: str,
                                   page_local_path: str):
        """Находит, скачивает и перезаписывает все ассеты на странице."""
        assets_to_download = set()

        # Скрипты
        for script in soup.find_all('script', src=True):
            assets_to_download.add(urljoin(actual_url, script['src']))

        # Стили и иконки
        for link in soup.find_all('link', href=True):
            rel = [r.lower() for r in link.get('rel', [])]
            if 'stylesheet' in rel or any('icon' in r for r in rel) or \
               link.get('as') in ('style', 'script', 'font', 'image'):
                assets_to_download.add(urljoin(actual_url, link['href']))

        # Изображения
        for img in soup.find_all('img', src=True):
            assets_to_download.add(urljoin(actual_url, img['src']))
        for source in soup.find_all('source', src=True):
            assets_to_download.add(urljoin(actual_url, source['src']))

        # srcset
        for tag in soup.find_all(lambda t: t.name in ('img', 'source') and t.has_attr('srcset')):
            for item in tag['srcset'].split(','):
                item = item.strip()
                if item:
                    parts = item.split()
                    if parts:
                        assets_to_download.add(urljoin(actual_url, parts[0]))

        # Inline стили url(...)
        css_blocks = []
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                urls = CSS_URL_REGEX.findall(style_tag.string)
                for u in urls:
                    clean_u = u.strip("'\"")
                    if clean_u and not clean_u.startswith(('data:', 'http:', 'https:', '//')):
                        assets_to_download.add(urljoin(actual_url, clean_u))
                css_blocks.append(style_tag)

        style_attrs = []
        for tag in soup.find_all(style=True):
            style_str = tag['style']
            urls = CSS_URL_REGEX.findall(style_str)
            for u in urls:
                clean_u = u.strip("'\"")
                if clean_u and not clean_u.startswith(('data:', 'http:', 'https:', '//')):
                    assets_to_download.add(urljoin(actual_url, clean_u))
            style_attrs.append(tag)

        # Фильтруем
        assets_to_download = {url for url in assets_to_download if not should_skip_url(url)}

        # Скачиваем параллельно
        if assets_to_download:
            logger.info("Найдено %d ресурсов для скачивания.", len(assets_to_download))
            download_tasks = {}
            for asset_url in assets_to_download:
                download_tasks[asset_url] = asyncio.create_task(
                    self._download_asset(asset_url, actual_url)
                )
            await asyncio.gather(*download_tasks.values(), return_exceptions=True)

            asset_map = {}
            for asset_url, task in download_tasks.items():
                try:
                    asset_map[asset_url] = task.result()
                except Exception:
                    asset_map[asset_url] = None
        else:
            asset_map = {}

        # Перезапись ссылок на ассеты
        for script in soup.find_all('script', src=True):
            abs_url = urljoin(actual_url, script['src'])
            if asset_map.get(abs_url):
                script['src'] = get_relative_path(page_local_path, asset_map[abs_url])

        for link in soup.find_all('link', href=True):
            abs_url = urljoin(actual_url, link['href'])
            if asset_map.get(abs_url):
                link['href'] = get_relative_path(page_local_path, asset_map[abs_url])

        for img in soup.find_all('img', src=True):
            abs_url = urljoin(actual_url, img['src'])
            if asset_map.get(abs_url):
                img['src'] = get_relative_path(page_local_path, asset_map[abs_url])

        for source in soup.find_all('source', src=True):
            abs_url = urljoin(actual_url, source['src'])
            if asset_map.get(abs_url):
                source['src'] = get_relative_path(page_local_path, asset_map[abs_url])

        # srcset rewrite
        for tag in soup.find_all(lambda t: t.name in ('img', 'source') and t.has_attr('srcset')):
            new_parts = []
            for item in tag['srcset'].split(','):
                item = item.strip()
                if not item:
                    continue
                parts = item.split()
                if parts:
                    abs_src_url = urljoin(actual_url, parts[0])
                    descriptor = parts[1] if len(parts) > 1 else ""
                    if asset_map.get(abs_src_url):
                        local_rel = get_relative_path(page_local_path, asset_map[abs_src_url])
                        new_parts.append(f"{local_rel} {descriptor}".strip())
                    else:
                        new_parts.append(item)
            if new_parts:
                tag['srcset'] = ", ".join(new_parts)

        # CSS blocks
        for style_tag in css_blocks:
            if style_tag.string:
                style_tag.string = self._rewrite_css_urls(
                    style_tag.string, actual_url, page_local_path, asset_map
                )

        for tag in style_attrs:
            tag['style'] = self._rewrite_css_urls(
                tag['style'], actual_url, page_local_path, asset_map
            )

    def _rewrite_css_urls(self, css_content: str, actual_url: str,
                          page_local_path: str, asset_map: dict) -> str:
        """Перезаписывает url(...) в CSS."""
        def replacer(match):
            orig_url = match.group(1).strip()
            clean_url = orig_url.strip("'\"")
            if not clean_url or clean_url.startswith(('data:', 'http:', 'https:', '//')):
                return match.group(0)
            abs_url = urljoin(actual_url, clean_url)
            if abs_url in asset_map and asset_map[abs_url]:
                rel_path = get_relative_path(page_local_path, asset_map[abs_url])
                return f"url('{rel_path}')"
            return match.group(0)
        return CSS_URL_REGEX.sub(replacer, css_content)

    # ─── Скачивание ассета ───────────────────────────────────────────────

    async def _download_asset(self, url: str, base_url: str) -> str | None:
        """Скачивает один ассет и сохраняет на диск."""
        if should_skip_url(url):
            return None

        absolute_url = urljoin(base_url, url)

        if not is_allowed_domain(absolute_url):
            return None

        local_path = url_to_local_path(absolute_url, LOGIN_URL)

        if local_path in self.downloaded_assets:
            return local_path

        filepath = os.path.join(self.output_dir, local_path)

        if os.path.exists(filepath):
            self.downloaded_assets.add(local_path)
            return local_path

        if not self.aiohttp_session:
            await self._init_aiohttp_session()

        try:
            async with self.aiohttp_session.get(absolute_url) as response:
                if response.status != 200:
                    logger.warning("Не удалось скачать (код %d): %s", response.status, absolute_url)
                    return None

                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > 15 * 1024 * 1024:
                    logger.warning("Ассет слишком большой: %s", absolute_url)
                    return None

                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                with open(filepath, 'wb') as f:
                    async for chunk in response.content.iter_chunked(65536):
                        f.write(chunk)

                self.downloaded_assets.add(local_path)

                # CSS — рекурсивно обрабатываем вложенные url(...)
                if local_path.endswith('.css'):
                    await self._process_css_file(filepath, absolute_url)

                return local_path

        except Exception as e:
            logger.error("Ошибка скачивания %s: %s", absolute_url, e)
            return None

    async def _process_css_file(self, filepath: str, css_url: str):
        """Обрабатывает скачанный CSS: скачивает вложенные url(...) ресурсы."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            urls = re.findall(r'url\(\s*[\'\"]?([^\'\"\)\#\?]+)[\'\"]?\s*\)', content)
            if not urls:
                return

            replacements = {}
            for rel_url in urls:
                rel_url_clean = rel_url.strip()
                if not rel_url_clean or rel_url_clean.startswith(('data:', 'http:', 'https:', '//')):
                    continue

                abs_url = urljoin(css_url, rel_url_clean)
                child_local = await self._download_asset(abs_url, css_url)
                if child_local:
                    css_local_dir = os.path.dirname(url_to_local_path(css_url, LOGIN_URL))
                    rel_path = os.path.relpath(child_local, start=css_local_dir).replace('\\', '/')
                    replacements[rel_url] = rel_path

            if replacements:
                for original, new in replacements.items():
                    content = content.replace(original, new)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)

        except Exception as e:
            logger.error("Ошибка обработки CSS %s: %s", filepath, e)

    # ─── Очистка HTML ────────────────────────────────────────────────────

    def _clean_all(self):
        """Очищает все скачанные HTML-файлы."""
        logger.info("Начало очистки HTML-файлов...")

        ignore_dirs = {'health', 'rs', 'api', 'esia-proxy', 'esia-rs', 'aas'}
        html_count = 0

        for root, dirs, files in os.walk(self.output_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for fname in files:
                if fname.endswith('.html') and not fname.startswith('%23'):
                    filepath = os.path.join(root, fname)
                    relative = os.path.relpath(filepath, self.output_dir)
                    self._clean_html_file(filepath, relative)
                    html_count += 1

        logger.info("Очистка завершена: %d HTML-файлов обработано.", html_count)

    def _clean_html_file(self, filepath: str, relative_filepath: str):
        """Очищает один HTML-файл: удаление скриптов, перезапись путей."""
        parts = relative_filepath.replace('\\', '/').split('/')
        depth = len(parts) - 1
        rel_root = '../' * depth if depth > 0 else './'

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()

        soup = BeautifulSoup(html, 'lxml')

        # Удаление <base>
        for base in soup.find_all('base'):
            base.decompose()

        # Удаление скриптов
        scripts_removed = 0
        for script in soup.find_all('script'):
            src = script.get('src', '')
            content = script.string or ''
            should_remove = False
            for bad in BAD_SCRIPTS:
                if bad in src or bad in content:
                    should_remove = True
                    break
            if should_remove:
                script.decompose()
                scripts_removed += 1

        # Перезапись link href
        for link in soup.find_all('link', href=True):
            link['href'] = to_relative(link['href'], rel_root)

        # Перезапись script src
        for script in soup.find_all('script', src=True):
            script['src'] = to_relative(script['src'], rel_root)

        # Перезапись img src
        for img in soup.find_all('img', src=True):
            img['src'] = to_relative(img['src'], rel_root)

        # srcset
        for tag in soup.find_all(lambda t: t.name in ('img', 'source') and t.has_attr('srcset')):
            new_parts = []
            for item in tag['srcset'].split(','):
                item = item.strip()
                if not item:
                    continue
                subparts = item.split()
                if subparts:
                    new_url = to_relative(subparts[0], rel_root)
                    descriptor = subparts[1] if len(subparts) > 1 else ""
                    new_parts.append(f"{new_url} {descriptor}".strip())
            tag['srcset'] = ", ".join(new_parts)

        # SVG xlink:href
        for svg_use in soup.find_all('use'):
            for attr in ('href', 'xlink:href'):
                if svg_use.has_attr(attr):
                    svg_use[attr] = to_relative(svg_use[attr], rel_root)

        # Inline styles
        def rewrite_css_text(css_text):
            if not css_text:
                return css_text
            def replacer(match):
                orig_url = match.group(1).strip("'\" ")
                new_url = to_relative(orig_url, rel_root)
                return f"url('{new_url}')"
            return re.sub(r'url\(\s*([^\)]+)\s*\)', replacer, css_text)

        for tag in soup.find_all(style=True):
            tag['style'] = rewrite_css_text(tag['style'])
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                style_tag.string = rewrite_css_text(style_tag.string)

        # Перезапись ссылок <a>
        for a in soup.find_all('a', href=True):
            orig_href = a['href']
            new_href = to_relative(orig_href, rel_root)
            if orig_href != new_href:
                a['href'] = new_href

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(str(soup))

        logger.debug("Очищен: %s (удалено %d скриптов)", relative_filepath, scripts_removed)

    # ─── Сборка (offline.js) ─────────────────────────────────────────────

    def _assemble(self):
        """Генерирует и инъектирует offline.js во все HTML-файлы."""
        logger.info("Генерация offline.js и инъекция в HTML...")

        # Генерируем offline.js
        offline_js = self._generate_offline_js()
        offline_path = os.path.join(self.output_dir, "offline.js")
        with open(offline_path, 'w', encoding='utf-8') as f:
            f.write(offline_js)
        logger.info("Сгенерирован offline.js (%d байт)", len(offline_js))

        # Инъектируем во все HTML
        ignore_dirs = {'health', 'rs', 'api', 'esia-proxy', 'esia-rs', 'aas'}
        injected = 0

        for root, dirs, files in os.walk(self.output_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for fname in files:
                if fname.endswith('.html') and not fname.startswith('%23'):
                    filepath = os.path.join(root, fname)
                    relative = os.path.relpath(filepath, self.output_dir).replace('\\', '/')
                    parts = relative.split('/')
                    depth = len(parts) - 1
                    rel_root = '../' * depth if depth > 0 else './'

                    self._inject_offline_js(filepath, rel_root)
                    injected += 1

        logger.info("offline.js инъектирован в %d файлов.", injected)

    def _inject_offline_js(self, filepath: str, rel_root: str):
        """Инъектирует ссылку на offline.js в HTML-файл."""
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()

        soup = BeautifulSoup(html, 'lxml')
        offline_src = f"{rel_root}offline.js"

        # Проверяем, не инъектирован ли уже
        already = any(
            script.get('src') == offline_src
            for script in soup.find_all('script')
        )
        if already:
            return

        new_script = soup.new_tag('script', src=offline_src)
        if soup.body:
            soup.body.append(new_script)
        else:
            soup.append(new_script)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(str(soup))

    def _generate_offline_js(self) -> str:
        """Генерирует содержимое offline.js с навигацией между страницами."""
        import json

        navigation_map = [
            {
                "page": "profile/personal.html",
                "selector": "button.card-button",
                "titleContains": "Паспорт РФ",
                "target": "profile/personal/id-doc.html",
            }
        ]

        nav_map_json = json.dumps(navigation_map, ensure_ascii=False, indent=4)

        # Пробуем загрузить шаблон из site_builder/templates/
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'site_builder', 'templates', 'offline.js'
        )

        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            return template.replace('__NAVIGATION_MAP__', nav_map_json)

        # Fallback: генерируем offline.js встроенный
        return self._generate_builtin_offline_js(nav_map_json)

    def _generate_builtin_offline_js(self, nav_map_json: str) -> str:
        """Встроенный генератор offline.js на случай отсутствия шаблона."""
        return f"""/**
 * Offline Interaction Script (auto-generated by autoload)
 * Обеспечивает навигацию между страницами и базовую интерактивность.
 */

(function() {{
    console.log("=== Offline Script Loaded ===");

    const NAVIGATION_MAP = {nav_map_json};

    // Toast notification
    const style = document.createElement('style');
    style.innerHTML = `
        .offline-toast {{
            position: fixed; top: 24px; left: 50%;
            transform: translateX(-50%) translateY(-100px);
            background-color: #0b1f33; color: #ffffff;
            padding: 12px 24px; border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 999999999; font-family: 'Lato', sans-serif;
            font-size: 14px; transition: transform 0.3s ease, opacity 0.3s ease;
            opacity: 0; display: flex; align-items: center; gap: 8px;
        }}
        .offline-toast.show {{
            transform: translateX(-50%) translateY(0); opacity: 1;
        }}
    `;
    document.head.appendChild(style);

    const toast = document.createElement('div');
    toast.className = 'offline-toast';
    toast.innerHTML = '<span>✓</span> <span class="offline-toast-text">Действие выполнено</span>';
    document.body.appendChild(toast);

    function showToast(text, duration = 3000) {{
        toast.querySelector('.offline-toast-text').innerText = text;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), duration);
    }}

    // Config-driven navigation
    const currentLoc = window.location.pathname;
    const pathParts = currentLoc.replace(/^\\//, '').split('/');
    let currentPagePath = pathParts.join('/');
    if (currentPagePath.endsWith('/')) currentPagePath += 'index.html';
    if (!currentPagePath.endsWith('.html')) currentPagePath += '.html';

    NAVIGATION_MAP.forEach(rule => {{
        if (currentPagePath === rule.page || currentPagePath.endsWith(rule.page)) {{
            document.addEventListener('click', (e) => {{
                const card = e.target.closest(rule.selector) || e.target.closest('.card-button, button.card-button');
                if (card) {{
                    if (rule.titleContains) {{
                        const cardText = card.innerText || card.textContent || '';
                        if (!cardText.toLowerCase().includes(rule.titleContains.toLowerCase())) return;
                    }}
                    if (e.target.closest('.doc-card-actions-panel, lk-doc-action-share, lk-doc-action-copy')) return;
                    e.preventDefault();
                    
                    // Calculate absolute path relative to site root
                    const pathname = window.location.pathname;
                    let prefix = "/";
                    const idx = pathname.indexOf(rule.page);
                    if (idx !== -1) {{
                        prefix = pathname.substring(0, idx);
                    }} else {{
                        const cleanRulePage = rule.page.replace(/\\.html$/, '');
                        const idxClean = pathname.indexOf(cleanRulePage);
                        if (idxClean !== -1) {{
                            prefix = pathname.substring(0, idxClean);
                        }}
                    }}
                    if (!prefix.endsWith('/')) {{
                        prefix += '/';
                    }}
                    
                    window.location.href = prefix + rule.target;
                }}
            }});
        }}
    }});

    // Back button handling
    document.addEventListener('click', (e) => {{
        const backBtn = e.target.closest('.back-link, .back-button');
        const isBackText = backBtn || (e.target.closest('a, button') && (e.target.closest('a, button').innerText || '').trim() === 'Назад');
        const finalBackBtn = backBtn || (isBackText ? e.target.closest('a, button') : null);
        if (finalBackBtn) {{
            e.preventDefault();
            if (window.history.length > 1 && document.referrer && document.referrer.includes(window.location.host)) {{
                window.history.back();
            }} else {{
                const pathname = window.location.pathname;
                let prefix = "/";
                const match = pathname.match(/^\\/(view\\/[^\\/]+\\/)/);
                if (match) {{
                    prefix = match[0];
                }}
                if (!prefix.endsWith('/')) {{
                    prefix += '/';
                }}
                window.location.href = prefix + 'profile/personal.html';
            }}
        }}
    }});

    // Intercept forms and action buttons
    document.addEventListener('click', (e) => {{
        const el = e.target.closest('lk-doc-action-share, lk-doc-action-copy');
        if (el) {{
            e.preventDefault();
            showToast("Офлайн-режим: действие имитировано!");
        }}
    }});

    // Active sidebar link highlighting
    document.querySelectorAll('a').forEach(link => {{
        const href = link.getAttribute('href');
        if (href && !href.startsWith('#') && !href.startsWith('http')) {{
            const cleanHref = href.split('#')[0].split('?')[0].replace(/\\.\\.\\//g, '').replace(/\\.\\//g, '');
            if (cleanHref && currentLoc.endsWith(cleanHref)) {{
                link.classList.add('active', 'selected');
                const parent = link.closest('.sidebar-item, li, lk-menu-item');
                if (parent) parent.classList.add('active', 'selected');
            }}
        }}
    }});

}})();
"""
