"""Russian and Serbian Latin UI. No network translation or fact inference."""
from decimal import Decimal
from html import escape
from urllib.parse import urlsplit
from telegram_bot.search_groups import GROUPS

STRINGS = {
 'subscribe': ('🔔 Подписаться', '🔔 Prati nove poslove'),
 'update_subscription': ('🔔 Обновить подписку', '🔔 Ažuriraj praćenje'),
 'my_subscription': ('🔔 Моя подписка', '🔔 Moje praćenje'),
 'sub_none': ('Подписка пока не настроена. Найдите вакансии и нажмите «Подписаться».', 'Praćenje još nije podešeno. Pronađite poslove i izaberite „Prati nove poslove“.'),
 'sub_active': ('Подписка включена', 'Praćenje je uključeno'),
 'sub_paused': ('Подписка на паузе', 'Praćenje je pauzirano'),
 'sub_off': ('Подписка отключена', 'Praćenje je isključeno'),
 'sub_blocked': ('Доставка приостановлена: бот не смог отправить сообщение', 'Slanje je pauzirano: bot nije mogao da pošalje poruku'),
 'sub_note': ('Присылаем только новые подходящие вакансии. После включения или изменения условий старые объявления не рассылаются. Язык уведомлений совпадает с языком интерфейса.', 'Šaljemo samo nove poslove koji odgovaraju uslovima. Nakon uključivanja ili izmene uslova ne šaljemo stare oglase. Obaveštenja su na jeziku interfejsa.'),
 'sub_edit': ('Изменить условия', 'Promeni uslove'),
 'sub_pause': ('⏸ Пауза', '⏸ Pauziraj'),
 'sub_resume': ('▶ Включить с новых вакансий', '▶ Uključi za nove poslove'),
 'sub_disable': ('Отключить подписку', 'Isključi praćenje'),
 'sub_saved': ('✅ Условия подписки сохранены.', '✅ Uslovi praćenja su sačuvani.'),
 'sub_unknown_yes': ('Включать вакансии без данных о зарплате: да', 'Uključi poslove bez podataka o zaradi: da'),
 'sub_unknown_no': ('Включать вакансии без данных о зарплате: нет', 'Uključi poslove bez podataka o zaradi: ne'),
 'menu': ('Главное меню', 'Glavni meni'),
 'new_job': ('🔔 Новая вакансия по вашей подписке', '🔔 Novi posao prema vašim uslovima'),
 'home': ('Поиск работы в Сербии. Выберите города, категории и при желании зарплату.', 'Pretraga poslova u Srbiji. Izaberite gradove, kategorije i, po želji, zaradu.'),
 'find': ('🔎 Найти вакансии', '🔎 Pronađi poslove'),
 'language': ('🌐 Язык интерфейса', '🌐 Jezik interfejsa'),
 'cities': ('📍 Город', '📍 Grad'),
 'categories': ('💼 Категория', '💼 Kategorija'),
 'all_cities': ('Вся Сербия', 'Cela Srbija'),
 'all_categories': ('Все категории', 'Sve kategorije'),
 'remote': ('Удалённая работа', 'Rad na daljinu'),
 'back': ('Назад', 'Nazad'),
 'next': ('Далее', 'Dalje'),
 'selected': ('Выбрано: ', 'Izabrano: '),
 'cities_hint': ('Можно выбрать несколько. Для удалённых вакансий отметьте «Удалённая работа».', 'Možete izabrati više gradova. Za rad od kuće označite „Rad na daljinu“.'),
 'categories_hint': ('Можно выбрать несколько категорий.', 'Možete izabrati više kategorija.'),
 'any_salary': ('Любая', 'Bilo koja'),
 'salary_min': ('От {amount} тыс. RSD', 'Od {amount} hiljada RSD'),
 'unknown_salary': ('Также без данных о зарплате', 'Uključi i poslove bez podataka o zaradi'),
 'show': ('Показать вакансии', 'Prikaži poslove'),
 'salary_hint': ('💰 Зарплата — необязательно. Сумма в RSD за месяц, нетто.\nДиапазон 100–150 тыс. подходит под «от 120 тыс.».\nОпция «без данных» включает и суммы, которые нельзя сравнить: другая валюта, период или неизвестное нетто/брутто. Полные условия будут в карточке.', '💰 Zarada nije obavezan filter. Iznos je mesečni, neto, u RSD.\nRaspon 100–150 hiljada odgovara izboru „od 120 hiljada“.\nOpcija „bez podataka“ uključuje i neuporedive iznose: drugu valutu, period ili nepoznat neto/bruto iznos. Puni uslovi prikazani su u oglasu.'),
 'shown': ('Показано вакансий: {count}.', 'Prikazano poslova: {count}.'),
 'empty': ('По этим условиям вакансий больше нет. Попробуйте изменить фильтры.', 'Nema više poslova koji odgovaraju ovim uslovima. Pokušajte da promenite filtere.'),
 'more': ('Ещё', 'Još'),
 'filters': ('Изменить фильтры', 'Promeni filtere'),
 'stale': ('Эта кнопка устарела. Откройте /start.', 'Ovo dugme više nije aktivno. Otvorite /start.'),
 'error': ('Не удалось завершить поиск. Попробуйте снова: /start.', 'Pretraga nije završena. Pokušajte ponovo: /start.'),
 'company_unknown': ('Компания не указана', 'Poslodavac nije naveden'),
 'city_unknown': ('Город не указан', 'Grad nije naveden'),
 'category': ('Категория', 'Kategorija'),
 'salary': ('Зарплата', 'Zarada'),
 'not_specified': ('не указана', 'nije navedena'),
 'from': ('от ', 'od '),
 'to': ('до ', 'do '),
 'currency_unknown': ('(валюта не указана)', '(valuta nije navedena)'),
 'period_unknown': ('период не указан', 'period nije naveden'),
 'basis_unknown': ('нетто/брутто не уточнено', 'neto/bruto nije navedeno'),
 'languages_unknown': ('Языковые требования не указаны', 'Jezički zahtevi nisu navedeni'),
 'deadline': ('Срок отклика', 'Rok za prijavu'),
 'apply': ('Подробнее / Откликнуться', 'Detaljnije / Prijavite se'),
}
GROUPS_SR = dict(zip(GROUPS, [
 'Prodaja i korisnička podrška', 'Administracija, finansije i upravljanje',
 'IT i digitalne profesije', 'Marketing i dizajn', 'Logistika, skladištenje i transport',
 'Proizvodnja i zanatski poslovi', 'Građevinarstvo i inženjerstvo',
 'Ugostiteljstvo, hotelijerstvo i turizam', 'Zdravstvo, obrazovanje i nega', 'Ostali poslovi']))
LANGUAGES = {
 'en': ('Английский','Engleski'), 'sr': ('Сербский','Srpski'), 'ru': ('Русский','Ruski'),
 'de': ('Немецкий','Nemački'), 'fr': ('Французский','Francuski'), 'it': ('Итальянский','Italijanski'), 'es': ('Испанский','Španski')}
OBLIGATIONS = {'REQUIRED':('обязателен','obavezan'), 'PREFERRED':('желателен','poželjan'),
 'NOT_REQUIRED':('не обязателен','nije obavezan'), 'UNKNOWN':('обязательность не уточнена','obaveznost nije navedena')}
PERIODS = {'MONTH':('в месяц','mesečno'), 'HOUR':('в час','po satu'), 'DAY':('в день','dnevno'), 'YEAR':('в год','godišnje')}
BASIS = {'NET':('нетто','neto'), 'GROSS':('брутто','bruto')}


def locale(session):
    return 'sr' if (session or {}).get('locale')=='sr' else 'ru'


def tr(lang, key, **values):
    return STRINGS[key][lang=='sr'].format(**values)


def group_label(key, lang):
    return (GROUPS_SR if lang=='sr' else GROUPS).get(key, tr(lang,'not_specified'))


def city_label(key, lang):
    if key=='__remote__': return tr(lang,'remote')
    if lang=='ru': return {'Beograd':'Белград','Novi Sad':'Нови-Сад'}.get(key,key)
    return key


def number(value):
    return format(Decimal(str(value)), ',.2f').rstrip('0').rstrip('.').replace(',', ' ').replace('.', ',')


def card(job, lang='ru'):
    from telegram_bot.localization import TITLES
    title=job['title']
    translated=job.get('title_'+lang)
    if not translated:
        pair=TITLES.get(title)
        translated=pair[0 if lang=='sr' else 1] if pair else None
    title=translated or title
    category=group_label(job.get('search_category'),lang)
    lines=['💼 <b>'+escape(title[:200])+'</b>',
           '🏢 '+escape((job.get('company') or tr(lang,'company_unknown'))[:140]),
           '📍 '+escape((tr(lang,'remote') if job.get('remote') else ', '.join(job.get('display_cities',job['cities'])) or tr(lang,'city_unknown'))[:180]),
           tr(lang,'category')+': '+escape(category)]
    pay=job.get('pay') or {}
    low,high=pay.get('min'),pay.get('max')
    if low is None and high is None:
        pay_text=tr(lang,'not_specified')
    else:
        if low is not None and high is not None:
            pay_text=number(low) if Decimal(str(low))==Decimal(str(high)) else number(low)+'–'+number(high)
        else:
            pay_text=tr(lang,'from')+number(low) if low is not None else tr(lang,'to')+number(high)
        pay_text+=' '+(pay.get('currency') or tr(lang,'currency_unknown'))
        pay_text+=', '+PERIODS.get(pay.get('period'),(tr(lang,'period_unknown'),)*2)[lang=='sr']
        pay_text+=', '+BASIS.get(pay.get('basis'),(tr(lang,'basis_unknown'),)*2)[lang=='sr']
    lines.append('💰 '+tr(lang,'salary')+': '+escape(pay_text))
    languages=[]
    for entry in job.get('languages') or []:
        name=LANGUAGES.get(entry['language'],(entry['language'],)*2)[lang=='sr']
        obligation=OBLIGATIONS.get(entry.get('requirement'),OBLIGATIONS['UNKNOWN'])[lang=='sr']
        text=name+' — '+obligation
        if entry.get('level'): text+=', '+entry['level']
        if text not in languages: languages.append(text)
    lines.append('🌐 '+escape(('; '.join(languages) or tr(lang,'languages_unknown'))[:450]))
    if job.get('deadline'): lines.append(tr(lang,'deadline')+': '+escape(str(job['deadline'])[:40]))
    url=job['source_url'];p=urlsplit(url)
    if p.scheme=='https' and p.hostname in {'poslovi.infostud.com','rs.jooble.org'} and not p.username:
        lines.append('<a href="'+escape(url,quote=True)+'">'+tr(lang,'apply')+'</a>')
    return '\n'.join(lines)
