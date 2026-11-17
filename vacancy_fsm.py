"""
FSM (Finite State Machine) для публикации вакансий
Пошаговый опрос для создания вакансии
"""
from aiogram.fsm.state import State, StatesGroup


class VacancyForm(StatesGroup):
    """Состояния для создания вакансии"""
    job_type = State()  # Тип вакансии: долгосрочная или разовая
    work_description = State()  # 1. Опишите вакансию/вид работы
    address = State()  # 2. Укажите адрес работы
    requirements = State()  # 3. Укажите требования (мальчик/девочка, с опытом/без опыта)
    payment = State()  # 4. Укажите оплату в цифрах
    schedule = State()  # 5. Укажите график/время работы
    people_needed = State()  # 6. Сколько человек требуется (1-10)


class EditVacancyForm(StatesGroup):
    """Состояния для редактирования отдельных полей вакансии"""
    edit_address = State()  # Редактирование адреса
    edit_title = State()  # Редактирование задачи
    edit_payment = State() # Редактирование оплаты  
    edit_contact = State()
    edit_requirements = State()  # Редактирование требований
    edit_schedule = State()  # Редактирование графика


class ConfirmWorkForm(StatesGroup):
    """Состояния для подтверждения выхода на работу"""
    confirm_work = State()  # Подтверждение выхода
    work_start_time = State()  # Время начала работы
    work_end_time = State()  # Время окончания работы


class RatingForm(StatesGroup):
    """Состояния для оценки работника"""
    rating = State()  # Оценка от 1 до 5

