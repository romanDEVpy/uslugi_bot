"""
Автономный инструмент для загрузки двух страниц профиля Госуслуг
и объединения их в единый офлайн-сайт.

Запуск:
    python run.py

Алгоритм:
    1. Открывает браузер для авторизации на gosuslugi.ru
    2. Ждёт нажатия Enter в консоли после входа
    3. Автоматически загружает:
       - https://lk.gosuslugi.ru/profile/personal
       - https://lk.gosuslugi.ru/profile/personal/id-doc
    4. Скачивает все ассеты (CSS, шрифты, изображения, скрипты)
    5. Очищает HTML (удаляет динамические скрипты, перезаписывает пути)
    6. Инъектирует offline.js для навигации между страницами
    7. Сохраняет результат в ./output/
"""

import asyncio
import sys
import os
import logging

# Добавляем корневую папку проекта в sys.path для поддержки вспомогательных модулей
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loader import GosuslugiLoader

def setup_logging():
    """Настраивает красивое логирование в консоль."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def main():
    setup_logging()
    logger = logging.getLogger("autoload")

    logger.info("=" * 70)
    logger.info("  АВТОНОМНЫЙ ЗАГРУЗЧИК ПРОФИЛЯ ГОСУСЛУГ")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Этот инструмент автоматически:")
    logger.info("  1. Откроет браузер для авторизации")
    logger.info("  2. Загрузит страницы профиля")
    logger.info("  3. Объединит их в офлайн-сайт")
    logger.info("")

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

    loader = GosuslugiLoader(output_dir=output_dir)

    try:
        asyncio.run(loader.run())
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем.")
        sys.exit(0)
    except Exception as e:
        error_msg = str(e)
        if "Executable doesn't exist" in error_msg or "playwright install" in error_msg.lower():
            logger.error("Ошибка: Браузер Chromium для Playwright не установлен!")
            logger.error("Для установки выполните: playwright install chromium")
        else:
            logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
