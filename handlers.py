import re
import time
import logging

from tinydb.operations import set
from main import bot, dp, db, User
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.types import Message
from config import ADMIN_ID, BOT_VERSION, SUPPORT
from keyboards import MAIN_MENU, SETTINGS_MENU, CHANGING_GROUP_MENU
from timetable_controller import does_group_exist, does_timetable_exist, show_timetable_for_today


# state
class UserInfo(StatesGroup):
    group = State()


# post-state
class Post(StatesGroup):
    text = State()
    confirm = State()


async def notify_admin(dp):
    """ Функция для уведомления администраторов о запуске бота."""
    text = f'<b>Бот запущен!</b>'
    try:
        for admin_id in ADMIN_ID:
            await bot.send_message(chat_id=admin_id, text=text, reply_markup=MAIN_MENU)
    except:
        logging.info(f'У администратора {admin_id} бот остановлен.')


async def bye_admin(dp):
    """ Функция для уведомления администраторов о завершении работы бота. """
    text = f'<b>Бот остановлен!</b>'
    try:
        for admin_id in ADMIN_ID:
            await bot.send_message(chat_id=admin_id, text=text, reply_markup=MAIN_MENU)
    except:
        logging.info(f'У администратора {admin_id} бот остановлен.')


@dp.message_handler(commands='start')
async def send_welcome(message: Message):
    """ После получения команды /start, проверяем зарегистрирован-ли пользователь в нашей БД.
    Если пользователь найден, продолжаем общаться с ним показывая меню.
    В противном случае, начинаем его регистрировать.
    """
    text_for_existing_user = f'Рад вас видеть снова, {message.chat.first_name}!'
    text_for_new_user = f'Доброго времени суток {message.chat.first_name}, я ваш бот' \
                        f' помощник!\n\nДавайте определим из какой вы ' \
                        f'группы. Пожалуйста, отправьте мне название своей группы.\n\n' \
                        f'Пример: <b>БПИ19-02</b> или <b>бпи19-02</b>'

    if db.search(User.id == message.chat.id):
        await message.answer(text_for_existing_user, reply_markup=MAIN_MENU)
    else:
        await UserInfo.group.set()
        await message.answer(text_for_new_user)


@dp.message_handler(text='/update')
async def update_bot(message: Message):
    """ По сути обновление меню бота, если он сломался у пользователья.
    P.S.: не критичный костыль."""
    update_text = f'Бот обновлён до версии <b>{BOT_VERSION}</b>!'
    await message.answer(update_text, reply_markup=MAIN_MENU)


@dp.message_handler(text='/send_post')
async def send_public_post(message: Message):
    """ Рассылка пользователям бота, пока только текстовое сообщение.
    Данной командой могут воспользоваться только администраторы.
    Начинает цикл подготовки к рассылке."""
    text_to_admin = 'Чтобы сделать рассылку, оптравьте текст.'
    not_allowed = 'Вам это делать нельзя! ;)'

    if str(message.chat.id) in ADMIN_ID:
        await Post.text.set()
        await message.answer(text_to_admin, reply_markup=MAIN_MENU)
    else:
        await message.answer(not_allowed, reply_markup=MAIN_MENU)


@dp.message_handler(state=Post.text)
async def got_text(message: Message, state: FSMContext):
    """ Функция для обработки текста для рассылки.
    P.S.: предпросмотр текста."""
    await state.update_data(text=message.text)

    text_before_confirmation = f'Ваш текст получен:\n\n{message.text}\n\n' \
                               f'Если хотите начать рассылку, отправьте ' \
                               f'<b>ДА</b>, для отмены - <b>НЕТ</b>.'
    await Post.confirm.set()
    await message.answer(text_before_confirmation, reply_markup=MAIN_MENU)


@dp.message_handler(lambda message: message.text.upper() == 'НЕТ', state=Post.confirm)
async def cancel_publication(message: Message, state: FSMContext):
    """ Команда для отмены рассылки. """
    await state.finish()
    cancellation_text = 'Действие отменено.'
    await message.answer(cancellation_text, reply_markup=MAIN_MENU)


@dp.message_handler(lambda message: message.text.upper() == 'ДА', state=Post.confirm)
async def publish(message: Message, state: FSMContext):
    """ Команда запускает рассылку.
    После окончания рассылка, только запустивший рассылку администратор
    получает уведомление и небольшую статистику."""
    users = db.all()

    counter = 0
    async with state.proxy() as data:
        for user in users:
            if counter % 10 == 0:
                time.sleep(0.5)
            await bot.send_message(chat_id=user['id'], text=data['text'], reply_markup=MAIN_MENU)
            counter += 1

    await state.finish()
    publication_ended_text = f'Рассылка закончена.\n\n' \
                             f'Ваше сообщение отправлено <b>{counter}</b> пользователям.'
    await message.answer(publication_ended_text, reply_markup=MAIN_MENU)


@dp.message_handler(lambda message: message.text == 'Отменить', state=UserInfo.group)
async def cancel_process(message: Message, state: FSMContext):
    """ Команда для отмены изменения группы пользователя. """
    await state.finish()
    text = 'Действие отменено.'
    await message.answer(text, reply_markup=SETTINGS_MENU)


@dp.message_handler(lambda message: not re.match(r'[а-яА-Я]{,5}\d{2}-\d{2}', message.text), state=UserInfo.group)
async def got_error_group_name(message: Message):
    """ Функция для проверки не валидности названия группы пользователя. """
    error_text = 'Вы указали название группы неправильно, пожалуйста соблюдайте строгий формат.\n\n' \
                 'Пример: <b>БПИ19-02</b> или <b>бпи19-02</b>'
    return await message.reply(error_text)


@dp.message_handler(lambda message: re.match(r'[а-яА-Я]{,5}\d{2}-\d{2}', message.text), state=UserInfo.group)
async def true_group_name(message: Message, state: FSMContext):
    """ Функция для проверки валидности названия группы пользователя. """
    await state.update_data(group=message.text.upper())
    needed_user = db.search(User.id == message.chat.id)

    async with state.proxy() as data:
        if needed_user:
            db.update(set('group', data['group']), User.id == message.chat.id)
        else:
            db.insert({'id': message.chat.id, 'group': data['group']})

    await state.finish()
    success_text = 'Ваш помощник всё запомнил, спасибо. Пользуйтесь функционалом на здоровье!'
    await message.answer(success_text, reply_markup=MAIN_MENU)


@dp.message_handler(text='🏠 Главное меню')
async def show_main_menu(message: Message):
    """ Команда для возвращения на главное меню. """
    text = 'Вы вернулись на главное меню.'
    await message.answer(text, reply_markup=MAIN_MENU)


@dp.message_handler(text='ℹ️ О боте')
async def show_statistics(message: Message):
    """ Команда для отображения информации о боте. """
    users = len(db)
    text = f'<b>О боте</b>\n\n' \
           f'Версия: {BOT_VERSION}\n' \
           f'Пользователей: {users}\n' \
           f'Тех. поддержка: {SUPPORT}\n\n' \
           f'Если вам не удобно пользоваться ботом, ' \
           f'можете скачать мобильное приложение для <a href="https://sibsau.ru">Android</a> ' \
           f'или <a href="https://sibsau.ru">iOS</a>.'
    await message.answer(text, reply_markup=SETTINGS_MENU)


@dp.message_handler(text='⚙️ Настройки')
async def show_settings(message: Message):
    """ Команда/раздел Настройки.
    Возвращает меню для данного раздела."""
    text = 'Выбирайте действие.'
    await message.answer(text, reply_markup=SETTINGS_MENU)


@dp.message_handler(text='👥 Изменить группу')
async def change_group(message: Message):
    """ Команда для изменения группы пользователя. """
    current_user = db.search(User.id == message.chat.id)
    current_group = current_user[0]['group']
    text = f'Ваша текущая группа: <b>{current_group}</b>.\n\n' \
           f'Если хотите изменить группу, пожалуйста отправьте ' \
           f'название новой группы.\n\n' \
           f'Пример: <b>БПИ19-02</b> или <b>бпи19-02</b>'
    await UserInfo.group.set()
    await message.answer(text, reply_markup=CHANGING_GROUP_MENU)


@dp.message_handler(text='🚀 Раcписание')
async def show_timetable(message: Message):
    """ Команда для отображения расписания пользователю. """
    timetable_fail_text = f'Раcписание для вашей группы ещё не добавлено.\n\n' \
                          f'Попробуйте через некоторое время или сообщите об ошибке:' \
                          f' {SUPPORT}'
    group_not_found_text = 'Кажется ваша группа не существует в нашей базе.\n\n' \
                           'Пожалуйста проверьте её, ' \
                           'изменить группу можно в:\nНастройки -> Изменить группу'

    current_user_id = message.chat.id
    current_user = db.search(User.id == current_user_id)
    current_user_group = current_user[0]['group']

    if await does_group_exist(current_user_group):
        if await does_timetable_exist(current_user_group):
            await show_timetable_for_today(current_user_id, current_user_group)
        else:
            await message.answer(timetable_fail_text, reply_markup=MAIN_MENU)
    else:
        await message.answer(group_not_found_text, reply_markup=MAIN_MENU)
