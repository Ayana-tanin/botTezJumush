"""
FSM (Finite State Machine) для публикации анкет
Пошаговый опрос для создания анкеты соискателя
"""
from aiogram.fsm.state import State, StatesGroup


class ResumeForm(StatesGroup):
    """Состояния для создания анкеты"""
    name = State()  # Имя
    age = State()  # Возраст
    gender = State()  # Пол (Мужской/Женский)
    experience = State()  # Опыт работы
    about = State()  # О себе
    phone = State()  # Телефон 0555123456


class EditResumeForm(StatesGroup):
    """Состояния для редактирования анкеты"""
    edit_name = State()
    edit_age = State()
    edit_gender = State()
    edit_experience = State()
    edit_about = State()
