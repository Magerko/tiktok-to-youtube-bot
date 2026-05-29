from aiogram.fsm.state import State, StatesGroup


class AddTikTok(StatesGroup):
    waiting_username = State()


class AddYouTube(StatesGroup):
    waiting_title = State()
    waiting_method = State()       # выбор: общий vs отдельный client_secrets
    waiting_secrets = State()      # ждём document с client_secrets.json


class AddPair(StatesGroup):
    pick_tiktok = State()
    pick_youtube = State()
    pick_mode = State()


class EditReviewTitle(StatesGroup):
    waiting_input = State()


class UploadCookies(StatesGroup):
    waiting_doc = State()
