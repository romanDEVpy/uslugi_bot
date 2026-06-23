import os
import sys
import asyncio
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Include root folder in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from autoload.loader import GosuslugiLoader

logger = logging.getLogger(__name__)

class GosuslugiWebLoader(GosuslugiLoader):
    """
    Web-friendly version of GosuslugiLoader that performs automated login
    via credentials, supports 2FA callbacks, and saves progress.
    """
    def __init__(self, output_dir: str, birth_date: str = ""):
        super().__init__(output_dir=output_dir)
        self.custom_birth_date = birth_date
        self.custom_passport = self._generate_passport_number()

    async def run_web(self, username, password, get_otp_callback, on_progress):
        """
        Executes the generation pipeline with credentials.
        
        :param username: Phone / Email / SNILS
        :param password: Password
        :param get_otp_callback: async callable returning OTP code (str)
        :param on_progress: async callable(status: str, message: str)
        """
        os.makedirs(self.output_dir, exist_ok=True)
        
        await on_progress("initializing", "Запуск виртуального браузера...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 800}
            )
            
            # Set extra headers to bypass basic detection
            await context.set_extra_http_headers({
                "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            })
            
            page = await context.new_page()
            
            await on_progress("navigating", "Переход на страницу входа Госуслуг...")
            
            # Start navigation
            try:
                await page.goto("https://lk.gosuslugi.ru/profile/personal", wait_until="load", timeout=40000)
            except Exception as e:
                logger.error(f"Navigation failed: {e}")
                await on_progress("failed", f"Не удалось загрузить сайт Госуслуг: {e}")
                await browser.close()
                return False

            # Wait for either profile loaded (already logged in) or redirect to login form
            await page.wait_for_timeout(3000)
            
            current_url = page.url
            if "esia.gosuslugi.ru" in current_url or "login" in current_url:
                await on_progress("authenticating", "Ввод логина и пароля...")
                
                try:
                    # Selectors for username
                    username_selectors = [
                        "#login",
                        "input[placeholder*='СНИЛС']",
                        "input[placeholder*='телефон']",
                        "input[placeholder*='почта']",
                        "input[type='text']"
                    ]
                    
                    username_input = None
                    for selector in username_selectors:
                        try:
                            el = page.locator(selector).first
                            if await el.is_visible(timeout=2000):
                                username_input = el
                                break
                        except Exception:
                            continue
                            
                    if not username_input:
                        raise ValueError("Не найдено поле ввода логина.")
                        
                    await username_input.fill(username)
                    await page.wait_for_timeout(500)
                    
                    # Selectors for password
                    password_selectors = [
                        "#password",
                        "input[type='password']"
                    ]
                    
                    password_input = None
                    for selector in password_selectors:
                        try:
                            el = page.locator(selector).first
                            if await el.is_visible(timeout=2000):
                                password_input = el
                                break
                        except Exception:
                            continue
                            
                    if not password_input:
                        raise ValueError("Не найдено поле ввода пароля.")
                        
                    await password_input.fill(password)
                    await page.wait_for_timeout(500)
                    
                    # Submit button
                    submit_button = page.locator("button[type='submit'], button:has-text('Войти'), .button-big").first
                    await submit_button.click()
                    await page.wait_for_timeout(3000)
                    
                except Exception as e:
                    logger.error(f"Login input failed: {e}")
                    await on_progress("failed", f"Ошибка ввода учетных данных: {e}")
                    await browser.close()
                    return False
                
                # Check for 2FA / OTP requirement
                await page.wait_for_timeout(2000)
                current_url = page.url
                
                # Detect if 2FA code is requested (OTP form)
                otp_input = None
                otp_selectors = [
                    "#code",
                    "input[autocomplete='one-time-code']",
                    "input[type='tel']"
                ]
                
                for selector in otp_selectors:
                    try:
                        el = page.locator(selector).first
                        if await el.is_visible(timeout=3000):
                            otp_input = el
                            break
                    except Exception:
                        continue
                
                if otp_input:
                    logger.info("2FA code requested by Gosuslugi.")
                    await on_progress("awaiting_otp", "Введите СМС-код или код из приложения TOTP...")
                    
                    try:
                        # Wait for user input via WebSocket callback
                        otp_code = await get_otp_callback()
                        if not otp_code:
                            raise ValueError("Код авторизации не был предоставлен.")
                            
                        await on_progress("submitting_otp", "Отправка кода подтверждения...")
                        await otp_input.fill(otp_code)
                        await page.wait_for_timeout(500)
                        
                        # Click verify/submit
                        verify_button = page.locator("button[type='submit'], button:has-text('Подтвердить'), .button-big").first
                        await verify_button.click()
                        await page.wait_for_timeout(5000)
                        
                    except Exception as e:
                        logger.error(f"OTP submission failed: {e}")
                        await on_progress("failed", f"Ошибка отправки кода OTP: {e}")
                        await browser.close()
                        return False

            # Check if login succeeded (redirected to lk.gosuslugi.ru/profile/personal)
            await page.wait_for_timeout(3000)
            if "lk.gosuslugi.ru" not in page.url:
                # Check if there is an error message visible on the login page
                error_msg = "Не удалось пройти авторизацию (возможно, неверный пароль или код 2FA)."
                try:
                    error_el = page.locator(".error-text, .alert-danger, .notification-item-error").first
                    if await error_el.is_visible(timeout=1000):
                        text = await error_el.inner_text()
                        if text:
                            error_msg = f"Ошибка Госуслуг: {text.strip()}"
                except Exception:
                    pass
                
                await on_progress("failed", error_msg)
                await browser.close()
                return False
                
            await on_progress("authenticated", "Успешный вход! Извлечение сессии...")
            
            # Extract cookies after login
            auth_cookies = await context.cookies()
            cookie_pairs = [f"{c['name']}={c['value']}" for c in auth_cookies]
            self.cookies_str = "; ".join(cookie_pairs)
            
            await on_progress("downloading", "Загрузка страниц профиля и ассетов...")
            await self._init_aiohttp_session()
            
            # Download Pages
            from autoload.loader import PAGES
            for page_info in PAGES:
                await on_progress("downloading", f"Скачивание страницы {page_info['local_name']}...")
                await self._fetch_and_save_page(page, page_info["url"], page_info["local_name"])
                await asyncio.sleep(1.0)
                
            await self._close_aiohttp_session()
            await browser.close()
            
        # Clean HTML
        await on_progress("processing", "Очистка HTML от динамических скриптов...")
        self._clean_all()
        
        # Assemble navigation
        await on_progress("processing", "Сборка оффлайн-навигации...")
        self._assemble()
        
        # Apply custom data
        await on_progress("processing", "Применение настроек персональных данных...")
        self._apply_custom_data()
        
        await on_progress("completed", "Готово! Сайт успешно сгенерирован.")
        return True
