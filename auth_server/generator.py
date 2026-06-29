import os
import sys
import shutil
import logging

# Include root folder in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from autoload.loader import GosuslugiLoader

logger = logging.getLogger(__name__)

# Path to the template site (copied from autoload/output during build)
TEMPLATE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "autoload", "output")
)


class TemplateSiteBuilder(GosuslugiLoader):
    """
    Шаблонный генератор сайтов.
    Берёт заранее скачанную копию (шаблон) и подставляет в неё
    пользовательские данные (ФИО + дата рождения).
    Не использует Playwright и не требует авторизации.
    """
    def __init__(self, output_dir: str, fio: str, birth_date: str, gender: str):
        super().__init__(output_dir=output_dir)
        self.custom_fio = fio.upper().strip()
        self.custom_birth_date = birth_date.strip()
        self.custom_gender = gender.strip()
        self.custom_passport = self._generate_passport_number()
        self.custom_issue_date = self._generate_issue_date(self.custom_birth_date)
        self.custom_inn = self._generate_inn()
        self.custom_snils = self._generate_snils()

    async def build(self, on_progress=None):
        """
        Выполняет шаблонную генерацию:
        1. Копирует шаблон в output_dir
        2. Подменяет персональные данные
        3. Пересобирает offline.js

        :param on_progress: async callable(status: str, message: str)
        :return: True если успешно
        """
        async def _progress(status, message):
            if on_progress:
                await on_progress(status, message)

        await _progress("initializing", "Подготовка шаблона сайта...")

        # Проверяем что шаблон существует
        if not os.path.exists(TEMPLATE_DIR):
            logger.error(f"Шаблон не найден: {TEMPLATE_DIR}")
            await _progress("failed", "Шаблон сайта не найден на сервере.")
            return False

        # Копируем шаблон в output_dir
        try:
            await _progress("downloading", "Копирование шаблона сайта...")
            if os.path.exists(self.output_dir):
                shutil.rmtree(self.output_dir)
            shutil.copytree(TEMPLATE_DIR, self.output_dir)
            logger.info(f"Шаблон скопирован: {TEMPLATE_DIR} → {self.output_dir}")
        except Exception as e:
            logger.error(f"Ошибка копирования шаблона: {e}")
            await _progress("failed", f"Ошибка копирования шаблона: {e}")
            return False

        # Подмена персональных данных
        await _progress("processing", "Применение персональных данных (ФИО, дата рождения)...")
        logger.info(
            f"Подмена данных: ФИО={self.custom_fio}, "
            f"ДР={self.custom_birth_date}, "
            f"Паспорт={self.custom_passport}, "
            f"Дата выдачи={self.custom_issue_date}, "
            f"ИНН={self.custom_inn}, "
            f"СНИЛС={self.custom_snils}"
        )
        self._apply_custom_data()

        # Пересборка offline.js
        await _progress("processing", "Сборка оффлайн-навигации...")
        self._assemble()

        await _progress("completed", "Готово! Сайт успешно сгенерирован.")
        logger.info(f"Шаблонная генерация завершена: {self.output_dir}")
        return True
