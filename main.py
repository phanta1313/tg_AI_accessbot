import asyncio
import logging
import sys
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram import types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ChatInviteLink
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from db import Base, User
from datetime import date, timedelta



load_dotenv()

BOT_TOKEN = getenv("BOT_TOKEN")
GROUP_ID = getenv("GROUP_ID")
GROUP_NAME = getenv("GROUP_NAME")
PAYMENT_PROVIDER_TOKEN = getenv("PAYMENT_PROVIDER_TOKEN")
POSTGRES_USER = getenv("POSTGRES_USER")
POSTGRES_PASSWORD = getenv("POSTGRES_PASSWORD")
POSTGRES_DB = getenv("POSTGRES_DB")
POSTGRES_HOST = getenv("POSTGRES_HOST")
DATABASE_URL = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)



@dp.message(Command(commands=["start", "команды"]))
async def show_commands(message: types.Message):
    commands_kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="/id"),
                KeyboardButton(text="/справка"),
            ],
            [
                KeyboardButton(text="/приобрести"),
                KeyboardButton(text="/команды"),
            ],
        ],
        resize_keyboard=True
    )

    text = (
        "Cписок доступных команд:\n"
        "/id — Узнать ID текущего чата или группы\n"
        "/справка — Получить справку о текущем состоянии подписки\n"
        f"/приобрести — Начать оплату и приобрести ссылку на {GROUP_NAME}\n"
        "/команды — Узнать возможные команды"
    )
    await message.answer(text, reply_markup=commands_kb)


@dp.message(Command(commands=["id"]))
async def get_chat_id(message: Message):
    chat_id = message.chat.id
    chat_type = message.chat.type
    await message.reply(f"💬 ID чата: `{chat_id}`\n📦 Тип: `{chat_type}`", parse_mode="Markdown")


@dp.message(Command(commands=["справка"]))
async def show_user_info(message: Message) -> None:
    username = message.from_user.username
    chat_id = message.chat.id

    async with async_session() as session:
        result = await session.execute(select(User).where(User.tg_username == username))
        user = result.scalars().first()
       
    if user and user.sub_expire_date and user.sub_expire_date > date.today():
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"Здравствуйте, <b>{username}</b>!👋\n\n"
                f"Дата истекания вашего срока подписки: <b>{user.sub_expire_date}</b>.\n"
                "Если хотите продлить еще на месяц - впишите команду /продлить.\n"
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
                f"Здравствуйте, <b>{username}</b>!👋 \n\n"
                f"На данный момент вы не состоите в группе <b>{GROUP_NAME}</b>.\n"
                f"Дата истекания вашей последней подписки - {is_expire_date_valid if is_expire_date_valid else "Вы ни разу не вступали в группу.\n"}"
                "Хотите стать частью нашего сообщества и получить весь материал по курсам?\n"
                "Впишите команду /приобрести для оплаты.\n"
                "После успешной оплаты вы получите одноразовую ссылку на группу."
            ),
            parse_mode="HTML"
        )


@dp.message(Command(commands=["приобрести"]))
async def sub_payment_test(message: Message):
    username = message.from_user.username
    expire_date = date.today() + timedelta(days=40)
    
    is_payment_successfull = True ##TODO: actual payment

    if not is_payment_successfull:
        await message.reply(f"Ошибка оплаты.")
    else:
        async with async_session() as session:
            query = insert(User).values(
                tg_username=username,
                sub_expire_date=expire_date
            ).on_conflict_do_update(
                index_elements=["tg_username"],  
                set_={"sub_expire_date": expire_date}
            )

            try:
                await session.execute(query)
                await session.commit()
                
                try:
                    invite_link: ChatInviteLink = await bot.create_chat_invite_link(
                                    chat_id=GROUP_ID,
                                    member_limit=1,
                                    creates_join_request=False, 
                                    name=f"Для @{message.from_user.username}"
                    )
                    await message.reply(f"Ваша персональная одноразовая ссылка:\n{invite_link.invite_link}")
                except Exception as e:
                        await message.reply(f"Ошибка при создании ссылки: {e}")

                await message.answer(f"✅ Тестовая подписка до {expire_date} оформлена!")

            except Exception as e:
                await session.rollback()
                await message.answer("⚠️ Произошла ошибка при сохранении в базу данных или платеже.")
                print(f"DB error: {e}")



async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    await init_models()
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())