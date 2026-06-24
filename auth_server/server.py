import os
import sys
import uuid
import logging
import asyncio
from datetime import datetime, timedelta
from aiohttp import web, WSMsgType
from aiogram import Bot

# Add root folder to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_server.config import auth_settings
from auth_server.generator import TemplateSiteBuilder
from bot.db.engine import async_session_maker
from bot.db.repositories import OrderRepository, HostedSiteRepository

logger = logging.getLogger("auth_server")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# In-memory dictionary for active generation sessions
# session_id -> { "order_id": int, "user_id": int, "telegram_id": int, "plan": str, "ws": WebSocket }
sessions = {}

# Folder where sites are generated
GENERATED_SITES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "generated_sites")
)
os.makedirs(GENERATED_SITES_DIR, exist_ok=True)

# Templates directory
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "auth_form.html")


async def handle_api_generate(request):
    """
    POST /api/generate
    Called by the Telegram bot to register a new generation session.
    """
    try:
        data = await request.json()
        order_id = data.get("order_id")
        user_id = data.get("user_id")
        telegram_id = data.get("telegram_id")
        plan = data.get("plan")
        
        if not all([order_id, user_id, telegram_id, plan]):
            return web.json_response({"error": "Missing parameters"}, status=400)
            
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            "order_id": order_id,
            "user_id": user_id,
            "telegram_id": telegram_id,
            "plan": plan,
            "ws": None,
        }
        
        logger.info(f"Registered generation session {session_id} for order {order_id}")
        return web.json_response({"session_id": session_id})
        
    except Exception as e:
        logger.error(f"Error registering session: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def handle_auth_page(request):
    """
    GET /auth/{session_id}
    Renders the data input form to the user.
    """
    session_id = request.match_info.get("session_id")
    if session_id not in sessions:
        return web.Response(text="<h1>Сессия не найдена или истекла</h1>", content_type="text/html", status=404)
        
    try:
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html")
    except Exception as e:
        logger.error(f"Error serving auth page: {e}")
        return web.Response(text="Internal Server Error", status=500)


async def generate_site_task(session_id: str, fio: str, birth_date: str, gender: str):
    """Background task that copies the template and substitutes user data."""
    session_data = sessions.get(session_id)
    if not session_data:
        return
        
    site_uuid = str(uuid.uuid4())
    output_dir = os.path.join(GENERATED_SITES_DIR, site_uuid)
    
    # Callback to send updates over websocket
    async def on_progress(status: str, message: str):
        ws = session_data.get("ws")
        if ws and not ws.closed:
            await ws.send_json({
                "type": "progress",
                "status": status,
                "message": message
            })

    bot = Bot(token=auth_settings.BOT_TOKEN)
    builder = TemplateSiteBuilder(
        output_dir=output_dir,
        fio=fio,
        birth_date=birth_date,
        gender=gender
    )
    
    async def auto_refund_stars(order_id: int):
        async with async_session_maker() as db_session:
            order_repo = OrderRepository(db_session)
            order = await order_repo.get_by_id(order_id)
            if not order:
                logger.error(f"Auto-refund failed: Order {order_id} not found.")
                return False
                
            if order.payment_method != "stars":
                logger.info(f"Auto-refund: Order {order_id} was paid via {order.payment_method}, skipping stars refund.")
                return False
                
            if order.status in ["refunded", "pending_payment"]:
                logger.info(f"Auto-refund: Order {order_id} has status {order.status}, skipping.")
                return False
                
            if not order.payment_id:
                logger.error(f"Auto-refund failed: Order {order_id} has no payment_id (charge ID).")
                return False
                
            logger.info(f"Initiating auto-refund of {order.amount_stars} Stars for order {order_id} (user {order.user.telegram_id})...")
            try:
                success = await bot.refund_star_payment(
                    user_id=order.user.telegram_id,
                    telegram_payment_charge_id=order.payment_id
                )
                if success:
                    order.status = "refunded"
                    await db_session.commit()
                    logger.info(f"Auto-refund succeeded for order {order_id}.")
                    
                    # Notify user about the refund
                    try:
                        refund_notice = (
                            "💸 **Автоматический возврат средств**\n\n"
                            "В связи с технической ошибкой при сборке вашего сайта, мы автоматически "
                            f"вернули вам `{order.amount_stars}` ⭐ за заказ `#{order.id}`.\n"
                            "Они уже зачислены обратно на ваш баланс Telegram."
                        )
                        await bot.send_message(
                            chat_id=order.user.telegram_id,
                            text=refund_notice,
                            parse_mode="Markdown"
                        )
                    except Exception as notify_err:
                        logger.warning(f"Failed to notify user about auto-refund: {notify_err}")
                    return True
                else:
                    logger.error(f"Auto-refund failed: Telegram API returned False.")
                    return False
            except Exception as refund_err:
                logger.error(f"Error executing auto-refund for order {order_id}: {refund_err}", exc_info=True)
                return False
    
    try:
        # Check if this is an extension order
        # format: "extend_{plan}_{site_uuid}"
        plan_str = session_data["plan"]
        is_extension = plan_str.startswith("extend_")
        
        success = await builder.build(on_progress=on_progress)
        
        if success:
            # Determine expiration duration
            # If extension, get the base plan: "day", "week", "month"
            actual_plan = plan_str.split("_")[1] if is_extension else plan_str
            duration_map = {
                "day": timedelta(days=1),
                "week": timedelta(weeks=1),
                "month": timedelta(days=30)
            }
            duration = duration_map.get(actual_plan, timedelta(days=1))
            
            # Save info to DB
            async with async_session_maker() as db_session:
                order_repo = OrderRepository(db_session)
                site_repo = HostedSiteRepository(db_session)
                
                expires_at = datetime.utcnow() + duration
                public_url = f"{auth_settings.SITE_BASE_URL}/{site_uuid}/profile/personal.html"
                
                if is_extension:
                    # Update existing site's expiration date
                    target_uuid = plan_str.split("_")[2]
                    extended_site = await site_repo.extend_expiration(target_uuid, duration)
                    if extended_site:
                        expires_at = extended_site.expires_at
                        public_url = extended_site.public_url
                        # Clean up the newly generated directory since we just extend the old one!
                        if os.path.exists(output_dir):
                            import shutil
                            shutil.rmtree(output_dir)
                    
                    await order_repo.mark_as_ready(
                        order_id=session_data["order_id"],
                        site_uuid=target_uuid,
                        site_url=public_url,
                        expires_at=expires_at
                    )
                else:
                    # Create hosted site record
                    await site_repo.create(
                        uuid=site_uuid,
                        order_id=session_data["order_id"],
                        user_id=session_data["user_id"],
                        local_path=output_dir,
                        public_url=public_url,
                        expires_at=expires_at
                    )
                    
                    await order_repo.mark_as_ready(
                        order_id=session_data["order_id"],
                        site_uuid=site_uuid,
                        site_url=public_url,
                        expires_at=expires_at
                    )
                
                await db_session.commit()
                
            # Send Success status via WS
            ws = session_data.get("ws")
            if ws and not ws.closed:
                await ws.send_json({
                    "type": "completed",
                    "site_url": public_url
                })
                
            # Notify user via Bot
            tg_msg = (
                "🎉 **Сайт успешно создан!**\n\n"
                f"Ваша оффлайн-копия Госуслуг доступна по ссылке:\n{public_url}\n\n"
                f"Хостинг активен до: {expires_at.strftime('%d.%m.%Y %H:%M UTC')}"
            )
            await bot.send_message(
                chat_id=session_data["telegram_id"],
                text=tg_msg,
                parse_mode="Markdown"
            )
            
        else:
            # Builder failed
            ws = session_data.get("ws")
            if ws and not ws.closed:
                await ws.send_json({
                    "type": "failed",
                    "message": "Генератор вернул ошибку выполнения."
                })
            
            await bot.send_message(
                chat_id=session_data["telegram_id"],
                text="❌ Возникла ошибка при генерации сайта. Попробуйте ещё раз."
            )
            await auto_refund_stars(session_data["order_id"])
            
    except Exception as e:
        logger.error(f"Task generation error: {e}", exc_info=True)
        ws = session_data.get("ws")
        if ws and not ws.closed:
            await ws.send_json({
                "type": "failed",
                "message": f"Критическая ошибка: {e}"
            })
            
        await bot.send_message(
            chat_id=session_data["telegram_id"],
            text=f"❌ Ошибка сборки сайта: {e}"
        )
        await auto_refund_stars(session_data["order_id"])
        
    finally:
        await bot.session.close()
        # Remove from active sessions
        sessions.pop(session_id, None)


async def handle_websocket(request):
    """
    GET /ws/{session_id}
    WebSocket endpoint for real-time interaction during generation.
    """
    session_id = request.match_info.get("session_id")
    if session_id not in sessions:
        return web.Response(text="Unauthorized", status=401)
        
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    session_data = sessions[session_id]
    session_data["ws"] = ws
    
    logger.info(f"WebSocket client connected for session {session_id}")
    
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = msg.json()
                msg_type = data.get("type")
                
                if msg_type == "generate":
                    fio = data.get("fio", "").strip()
                    birth_date = data.get("birth_date", "").strip()
                    gender = data.get("gender", "Мужской").strip()
                    
                    if not fio or not birth_date or not gender:
                        await ws.send_json({"type": "failed", "message": "Заполните все поля формы"})
                        continue
                        
                    # Start background generation task
                    asyncio.create_task(
                        generate_site_task(session_id, fio, birth_date, gender)
                    )
                        
            elif msg.type == WSMsgType.ERROR:
                logger.error(f"WS error: {ws.exception()}")
                
    finally:
        logger.info(f"WebSocket client disconnected for session {session_id}")
        if session_data.get("ws") == ws:
            session_data["ws"] = None
            
    return ws


async def init_app():
    app = web.Application()
    
    # Register routes
    app.router.add_post("/api/generate", handle_api_generate)
    app.router.add_get("/auth/{session_id}", handle_auth_page)
    app.router.add_get("/ws/{session_id}", handle_websocket)
    
    # Route for serving static generated websites
    # URL format: /view/{site_uuid}/...
    app.router.add_static("/view/", path=GENERATED_SITES_DIR, show_index=True)
    
    return app


if __name__ == "__main__":
    app = asyncio.run(init_app())
    web.run_app(
        app,
        host=auth_settings.AUTH_SERVER_HOST,
        port=auth_settings.AUTH_SERVER_PORT
    )
