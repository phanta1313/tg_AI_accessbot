import asyncio, logging, aiohttp
from datetime import date, timedelta
from os import getenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ChatInviteLink, LabeledPrice, PreCheckoutQuery, \
    ContentType
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from colorama import Fore, Style
from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from motor.motor_asyncio import AsyncIOMotorClient

from middleware import LoggingMiddleware
from db import Base, User



load_dotenv()


bot = Bot(token=getenv("BOT_TOKEN"), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.message.middleware(LoggingMiddleware())

postgres_engine = create_async_engine(getenv("POSTGRES_URL"), echo=True)
async_ps_session = sessionmaker(bind=postgres_engine, expire_on_commit=False, class_=AsyncSession)
mongo_client = AsyncIOMotorClient(getenv("MONGO_URL"))
mongo_db = mongo_client[getenv("MONGO_DB")]


GROUP_ID = getenv("GROUP_ID")
GROUP_NAME = getenv("GROUP_NAME")
PAYMENT_PROVIDER_TOKEN_TEST = getenv("PAYMENT_PROVIDER_TOKEN_TEST")

SUB_TITLE = "Доступ к группе"
SUB_DESCRIPTION = "Подписка на 30 дней"
SUB_PRICE = 10000 # *0.01
AI_MODEL = "accessbot_model"



############################
## AI PROMT CONFIGURATION ##
############################
async def ai_prompt(dataset: list[dict]):
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": AI_MODEL,  
        "messages": dataset,
        "stream": False,
        "max_new_tokens": 2048
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            data = await response.json()
            return data.get("message", {}).get("content", "")



#####################
## BOT INTERACTION ##
#####################
@dp.message(Command(commands=["start"]))
async def on_start(message: Message):
    thinking_msg = await message.answer("🤔 ИИ думает...\n(подождите пожалуйста ему не хватает мощности)\n\n/help")
    ai_response = await ai_prompt([{"role": "user", "content": f"Поприветствуй меня и предложи свою помощь"}])
    await thinking_msg.edit_text(ai_response)


@dp.message(F.text & ~F.text.startswith('/'))
async def on_message(message: Message):
    collection = mongo_db[str(message.from_user.id)]
    await collection.insert_one({"role":"user", "content": message.text})

    cursor = collection.find()
    current_dataset = []
    async for doc in cursor:
        current_dataset.append({
            "role": doc["role"],
            "content": doc["content"]
        })

    thinking_msg = await message.answer("🤔 ИИ думает...\n\nhelp")
    ai_response = await ai_prompt(current_dataset)
    await collection.insert_one({"role": "assistant", "content": ai_response})
    await thinking_msg.edit_text(ai_response)


@dp.message(Command(commands=["help"]))
async def show_commands(message: Message):
    commands_kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="/id"),
                KeyboardButton(text="/my_subscription"),
            ],
            [
                KeyboardButton(text="/payment"),
                KeyboardButton(text="/help"),
            ],
        ],
        resize_keyboard=True
    )

    text = (
        f"Здравствуйте, {message.from_user.first_name} 👋\n"
        "Чтобы начать, ознакомтесь со списком команд оплаты и получения справки о текущей подписке:\n\n"
        "/my_subscription — Получить справку о текущем состоянии подписки ℹ️\n"
        f"/payment — Начать оплату и приобрести ссылку на {GROUP_NAME} (пока что воспользуйтесь тестовой картой: /credit_card)💸\n\n"
        "⚠️ Важно: подписка дается на 30 дней, и перестает быть действительной в день истекания срока в 00:00\n\n"
        "Еще:\n"
        "/id — Узнать ID текущего чата или группы\n"
        "/help — Вывести это сообщение\n"
        "/credit_card - получить данные тестовой карты"
    )
    await message.answer(text, reply_markup=commands_kb)


@dp.message(Command(commands=["id"]))
async def get_chat_id(message: Message):
    chat_id = message.chat.id
    chat_type = message.chat.type
    await message.reply(f"💬 ID чата: `{chat_id}`\n📦 Тип: `{chat_type}`", parse_mode="Markdown")


@dp.message(Command(commands=["my_subscription"]))
async def show_user_info(message: Message) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id

    async with async_ps_session() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalars().first()

    if user and user.sub_expire_date and user.sub_expire_date > date.today():
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"Дата истекания срока вашей подписки: <b>{user.sub_expire_date}</b>.\n"
                "Если хотите продлить на месяц - можете еще раз воспользоваться командой /payment 💸\n"
                "И получить 10 дней в подарок ! 🧠"
            ),
            parse_mode="HTML"
        )
    else:
        try:
            is_expire_date_valid = user.sub_expire_date
        except:
            is_expire_date_valid = False

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"На данный момент вы не состоите в группе <b>{GROUP_NAME}</b>.\n"
                f"Дата истекания вашей последней подписки - {is_expire_date_valid if is_expire_date_valid else 'Вы ни разу не вступали в группу.'}\n"
                "Хотите стать частью нашего сообщества и получить весь материал по курсам?\n"
                "Впишите команду /приобрести для оплаты. 💸\n"
                "После успешной оплаты вы получите одноразовую ссылку на группу. ✅"
            ),
            parse_mode="HTML"
        )


@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name

    async with async_ps_session() as session:
        user_q = select(User).where(User.user_id == user_id)
        result = await session.execute(user_q)
        user = result.scalars().first()

        if user:
            if user.sub_expire_date >= date.today():
                expire_date = user.sub_expire_date + timedelta(days=40)
                query = update(User).where(User.user_id == user_id).values(sub_expire_date=expire_date, first_name=first_name)

                text = (
                        f"✅ Подписка продлена до {expire_date}!\n"
                        f"Благодарим за то что остаетесь с нами !"
                    )
            else:
                expire_date = date.today() + timedelta(days=30)
                query = update(User).values(sub_expire_date=expire_date, first_name=first_name)

                text = (
                    f"✅ Подписка офрмлена до {expire_date}!\n"
                    f"Рады видеть вас снова !"
                )
        else:
            expire_date = date.today() + timedelta(days=30)
            query = insert(User).values(user_id=user_id,sub_expire_date=expire_date, first_name=first_name)

            text = (
                f"✅ Подписка офрмлена до {expire_date}!\n"
                f"Добро пожаловать !"
            )

        try:
            await session.execute(query)
            await session.commit()

            try:
                invite_link: ChatInviteLink = await bot.create_chat_invite_link(
                                chat_id=GROUP_ID,
                                member_limit=1,
                                expire_date=timedelta(days=30),
                                creates_join_request=False,
                                name=f"Для @{message.from_user.first_name}"
                )
                await message.reply(f"Ваша персональная ссылка (действует пока активна подписка):\n{invite_link.invite_link}")
            except Exception as e:
                    await message.reply(f"Ошибка при создании ссылки: {e}")

            await message.answer(text)

        except Exception as e:
            await session.rollback()
            await message.answer("⚠️ Произошла ошибка при сохранении в базу данных или платеже.")
            print(f"DB error: {e}")


@dp.pre_checkout_query(lambda q: True)
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(Command(commands=["payment"]))
async def sub_payment_test(message: Message):
    prices = [
        LabeledPrice(label="Подписка на 30 дней", amount=SUB_PRICE)
    ]

    payload = f"{message.from_user.id}:{message.from_user.username}"
    await message.answer_invoice(
        title="Подписка на группу",
        description=f"Оплата доступа к группе {GROUP_NAME} на 30 дней",
        provider_token=PAYMENT_PROVIDER_TOKEN_TEST,
        currency="USD",
        prices=prices,
        start_parameter="subscription-start",
        payload=payload
    )


@dp.message(Command(commands=["credit_card"]))
async def display_card_info(message: Message):
    await message.answer("4548819407777774\n" \
                        "12/26\n123")



################
## CRON JOBS ##
################
async def notify_expired_members() -> None:
    async with async_ps_session() as session:
        query = await session.execute(select(User).where(User.sub_expire_date > date.today()))
        users = query.scalars().all()

        for user in users:
            expire_days = user.sub_expire_date - date.today()

            if expire_days.days == 5:
                text_message = (f"Здравствуйте, {user.first_name} 👋\n"
                                "До окончания вашей подписки осталось 5 дней. ⏱️\n"
                                "Желаете продлить?\n"
                                "/payment")
                await bot.send_message(user.user_id, text_message)

            if expire_days.days == 1:
                text_message = (f"Здравствуйте, {user.first_name} 👋\n"
                                "Ваша подписка заканчивается уже завтра. ❗\n"
                                "Желаете продлить?\n"
                                "/payment")
                await bot.send_message(user.user_id, text_message)



async def delete_expired_members() -> None:
    async with async_ps_session() as session:
        query = await session.execute(select(User).where(User.sub_expire_date < date.today()))
        users = query.scalars().all()

        for user in users:
            member = await bot.get_chat_member(chat_id=GROUP_ID, user_id=user.user_id)
            if not member.status == "creator":
                await bot.ban_chat_member(chat_id=GROUP_ID, user_id=user.user_id)
                await bot.send_message(user.user_id, f"Вы были исключены из {GROUP_NAME}.", parse_mode="Markdown")


async def trim_all_collections():
    max_documents=10000
    collections = await mongo_db.list_collection_names()
    
    for name in collections:
        collection = mongo_db[name]
        count = await collection.count_documents({})
        to_delete = count - max_documents

        if count > max_documents:
            cursor = collection.find({}, sort=[("_id", 1)], limit=to_delete)
            ids = [doc["_id"] async for doc in cursor]
            await collection.delete_many({"_id": {"$in": ids}})
            logging.info(f"Trimmed {to_delete} old docs from collection: {name}")



#####################
## INITTIALIZATION ##
#####################
async def init_models():
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    await init_models()

    await notify_expired_members()
    await delete_expired_members()
    await trim_all_collections()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(delete_expired_members, "cron", hour=0, minute=0, timezone="Europe/Moscow")
    scheduler.add_job(notify_expired_members, "cron", hour=0, minute=0, timezone="Europe/Moscow")
    scheduler.add_job(trim_all_collections, "cron", hour=0, minute=0, timezone="Europe/Moscow")
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=f"{Fore.GREEN}%(asctime)s{Style.RESET_ALL} | {Fore.BLUE}%(levelname)s{Style.RESET_ALL} | {Fore.YELLOW}%(name)s{Style.RESET_ALL} | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    asyncio.run(main())
