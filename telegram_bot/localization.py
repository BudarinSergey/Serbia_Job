"""Reviewed Serbian/Russian wording; unknown free text is never guessed."""
from decimal import Decimal


class TranslationRequired(ValueError):
    pass


# Source title -> Serbian (Latin), Russian. Company names are never translated.
TITLES = {
 'Operater u proizvodnji': ('Operater u proizvodnji','Оператор производства'),
 'Električar za održavanje pogona': ('Električar za održavanje pogona','Электрик по обслуживанию производственного оборудования'),
 'Visual Content Designer (Foto · Video · AI)': ('Dizajner vizuelnog sadržaja (foto · video · AI)','Дизайнер визуального контента (фото · видео · ИИ)'),
 'Specijalista za nabavku': ('Specijalista za nabavku','Специалист по закупкам'),
 'Magacinski radnik': ('Magacinski radnik','Работник склада'),
 'Operater na pakerici': ('Operater na pakerici','Оператор упаковочной машины'),
 'Junior HR menadžer': ('Mlađi menadžer za ljudske resurse','Младший менеджер по персоналу'),
 'Agent prodaje u call centru (rad iz kancelarije)': ('Agent prodaje u pozivnom centru (rad iz kancelarije)','Специалист по продажам в колл-центре (работа в офисе)'),
 'Prodavac - kasir': ('Prodavac — kasir','Продавец-кассир'),
 'Truck Driver Recruiter': ('Regruter vozača kamiona','Специалист по подбору водителей грузовиков'),
 'Magacioner': ('Magacioner','Кладовщик'),
 'Magacioneri potrebni .': ('Potrebni magacioneri','Требуются кладовщики'),
 'Potrebni radnici-magacioneri.': ('Potrebni radnici-magacioneri','Требуются работники склада'),
 'Magacioneri za rad 8h/vikend slobodan': ('Magacioneri — rad 8 sati, slobodan vikend','Работники склада — 8-часовой рабочий день, выходные свободны'),
 'Magacioner m/ž - Dobanovci': ('Magacioner (m/ž) — Dobanovci','Кладовщик (м/ж) — Добановци'),
 'Magacioner/FIZICKI RADNIK/ slobodan vikend': ('Magacioner / fizički radnik — slobodan vikend','Кладовщик / разнорабочий — выходные свободны'),
 'Magacioner - Makiš - m/ž': ('Magacioner (m/ž) — Makiš','Кладовщик (м/ж) — Макиш'),
 'Magacioner - M/Ž u štampariji': ('Magacioner (m/ž) u štampariji','Кладовщик (м/ж) в типографии'),
 'Kontrolor robe': ('Kontrolor robe','Контролёр товаров'),
 'Software Engineer II': ('Softverski inženjer II','Инженер-программист II'),
 'Diplomirani farmaceut': ('Diplomirani farmaceut','Дипломированный фармацевт'),
 'Menadžer za marketing i komunikacije': ('Menadžer za marketing i komunikacije','Менеджер по маркетингу и коммуникациям'),
 'Office Assistant na recepciji/Recepcioner': ('Administrativni asistent na recepciji / recepcioner','Административный ассистент на ресепшене / администратор'),
 'Cost control menadžer': ('Menadžer kontrole troškova','Менеджер по контролю затрат'),
 'Elektroinstalater/Električar za Expo': ('Elektroinstalater / električar za Expo','Электромонтажник / электрик для Expo'),
 'Kasir - prodavac': ('Kasir — prodavac','Кассир-продавец'),
 'Odgovorni projektant termotehničkih instalacija': ('Odgovorni projektant termotehničkih instalacija','Ответственный проектировщик теплотехнических систем'),
 'Odgovorni projektant građevinskih konstrukcija': ('Odgovorni projektant građevinskih konstrukcija','Ответственный проектировщик строительных конструкций'),
 'Odgovorni projektant elektro instalacija': ('Odgovorni projektant elektroinstalacija','Ответственный проектировщик электроустановок'),
 'Inženjer pripreme ponuda MEP instalacije': ('Inženjer pripreme ponuda za MEP instalacije','Инженер по подготовке предложений для инженерных систем MEP'),
 'Menadžer prodaje u hotelu': ('Menadžer prodaje u hotelu','Менеджер по продажам в отеле'),
 'Junior DevOps Engineer': ('Mlađi DevOps inženjer','Младший DevOps-инженер'),
 'Rukovodilac logistike i administracije prodaje': ('Rukovodilac logistike i administracije prodaje','Руководитель логистики и административного сопровождения продаж'),
 'Junior Network & Connectivity Engineer': ('Mlađi inženjer mreža i povezivanja','Младший инженер по сетям и подключениям'),
 'Odgovorni izvođač elektro radova': ('Odgovorni izvođač elektro radova','Ответственный производитель электромонтажных работ'),
 'Saradnik u finansijama': ('Saradnik u finansijama','Специалист по финансам'),
 'IT Support Specialist': ('Specijalista za IT podršku','Специалист технической поддержки IT'),
 'Asistent šefa magacina – prijem robe': ('Asistent šefa magacina — prijem robe','Помощник начальника склада — приём товаров'),
 'Logistics Coordinator in Trucking Brokerage': ('Koordinator logistike u posredovanju u drumskom transportu','Координатор логистики в транспортно-брокерской компании'),
 'Operater na presama': ('Operater na presama','Оператор прессов'),
 'Vaspitač': ('Vaspitač','Воспитатель'),
 'Tehničar održavanja': ('Tehničar održavanja','Техник по обслуживанию'),
 'Mašinski inženjer na održavanju građevinske mehanizacije': ('Mašinski inženjer za održavanje građevinske mehanizacije','Инженер-механик по обслуживанию строительной техники'),
 'Viljuškarista na čeonom i visokoregalnom viljuškaru': ('Viljuškarista na čeonom i visokoregalnom viljuškaru','Водитель фронтального погрузчика и высотного штабелёра'),
 'Tourism Administration & Accounting Officer': ('Saradnik za administraciju i računovodstvo u turizmu','Специалист по административной работе и учёту в туризме'),
 'Smenovođa odeljenja mesara – Banjica': ('Smenovođa odeljenja mesara — Banjica','Начальник смены мясного отдела — Баница'),
 'Smenovođa odeljenja ribarnice – Banjica': ('Smenovođa odeljenja ribarnice — Banjica','Начальник смены рыбного отдела — Баница'),
 'Vozač autotransportera': ('Vozač autotransportera','Водитель автовоза'),
 'Prodavac': ('Prodavac','Продавец'),
 'Vozač kombi vozila': ('Vozač kombi vozila','Водитель фургона / микроавтобуса'),
 'Vozač C kategorije': ('Vozač C kategorije','Водитель категории C'),
 'Šef tehničkog održavanja': ('Šef tehničkog održavanja','Руководитель технического обслуживания'),
 'Korporativni pravnik': ('Korporativni pravnik','Корпоративный юрист'),
 'Prodajni savetnik u luksuznoj modi': ('Prodajni savetnik u luksuznoj modi','Продавец-консультант люксовой одежды'),
 'Radnik u knjigovodstvu i administraciji': ('Radnik u knjigovodstvu i administraciji','Сотрудник бухгалтерии и административного отдела'),
 'Serviser Tetra Pak i procesne opreme': ('Serviser Tetra Pak i procesne opreme','Сервисный специалист по оборудованию Tetra Pak и технологическому оборудованию'),
 'Customs Documentation Specialist': ('Specijalista za carinsku dokumentaciju','Специалист по таможенной документации'),
 'Električar': ('Električar','Электрик'),
 'Tehničar za održavanje': ('Tehničar za održavanje','Техник по обслуживанию'),
 'Prodavac u pekari': ('Prodavac u pekari','Продавец в пекарне'),
 'Konobar/Šanker': ('Konobar / šanker','Официант / бармен'),
 'Magacioner': ('Magacioner','Кладовщик'),
 'Saradnik za poslove logistike': ('Saradnik za poslove logistike','Специалист по логистике'),
 'Planning and Quantity Survey Engineer Assistant': ('Asistent inženjera za planiranje i obračun količina','Ассистент инженера по планированию и расчёту объёмов работ'),
 'Smenovođa magacina – Banjica': ('Smenovođa magacina — Banjica','Начальник смены склада — Баница'),
 'Knjigovođa za materijalno knjigovodstvo': ('Knjigovođa za materijalno knjigovodstvo','Бухгалтер по учёту материальных ценностей'),
 'Referent - administrator u auto-školi': ('Referent — administrator u auto-školi','Делопроизводитель-администратор автошколы'),
 'Operations Specialist – Ocean Freight/Road Freight': ('Operativni specijalista za pomorski / drumski transport','Операционный специалист по морским / автомобильным перевозкам'),
 'Vozač kamiona za međunarodni transport sa C, E kategorijom': ('Vozač kamiona za međunarodni transport sa C, E kategorijom','Водитель международных грузоперевозок категорий C, E'),
 'Rukovalac građevinske mehanizacije': ('Rukovalac građevinske mehanizacije','Машинист строительной техники'),
 'Kuvar/Kuvarica': ('Kuvar / kuvarica','Повар'),
 'Senior računovođa': ('Senior računovođa','Старший бухгалтер'),
 'Farmaceutski tehničar': ('Farmaceutski tehničar','Фармацевтический техник'),
 'IT tehničar': ('IT tehničar','IT-техник'),
 'Senior Legal Advisor': ('Viši pravni savetnik','Старший юридический консультант'),
}

EDUCATION = {
 'VSS': ('Visoka stručna sprema (VSS)','Высшее образование (VSS)'),
 'SSS': ('Srednja stručna sprema (SSS)','Среднее профессиональное образование (SSS)'),
 'minimum III stepen SSS': ('Najmanje III stepen stručne spreme (SSS)','Не ниже III ступени профессионального образования (SSS)'),
 'Najmanje III stepen stručne spreme': ('Najmanje III stepen stručne spreme','Не ниже III ступени профессионального образования'),
 'Osnovna škola': ('Osnovna škola','Основное образование (osnovna škola)'),
 'Dobro opšte tehničko obrazovanje i iskustvo, poznavanje rada na pakerici je prednost': ('Dobro opšte tehničko obrazovanje i iskustvo; poznavanje rada na pakerici je prednost','Хорошее общее техническое образование и опыт; знание работы на упаковочной машине будет преимуществом'),
 'Minimum III stepen stručne spreme': ('Najmanje III stepen stručne spreme','Не ниже III ступени профессионального образования'),
 'University degree or relevant diploma in Civil Engineering, Quantity Surveying, Construction Management or a related field.': ('Univerzitetska diploma ili odgovarajuća diploma iz građevinarstva, obračuna količina i troškova, upravljanja izgradnjom ili srodne oblasti','Университетская или соответствующая профильная дипломная квалификация в строительстве, расчёте объёмов и стоимости работ, управлении строительством или смежной области'),
 'Srednja škola': ('Srednje obrazovanje','Среднее образование'),
 'Fakultet': ('Fakultetsko obrazovanje','Высшее образование'),
 'Viša / visoka škola': ('Viša / visoka škola','Высшая школа (viša / visoka škola)'),
 'Minimum SSS': ('Najmanje srednja stručna sprema (SSS)','Не ниже среднего профессионального образования (SSS)'),
 'minimum SSS': ('Najmanje srednja stručna sprema (SSS)','Не ниже среднего профессионального образования (SSS)'),
 'poželjno VSS ekonomskog ili srodnog usmerenja': ('Visoka stručna sprema ekonomskog ili srodnog usmerenja','Высшее экономическое или смежное образование'),
 'VSS ili SSS ekonomske ili srodne struke': ('Visoka ili srednja stručna sprema ekonomske ili srodne struke','Высшее или среднее профессиональное образование экономического или смежного профиля'),
 'VSS, po mogućstvu ekonomski ili menadžment smer': ('Visoka stručna sprema; po mogućstvu ekonomija ili menadžment','Высшее образование; предпочтительно экономика или менеджмент'),
 '• Min III ili IV stepen stručne spreme elektro struke': ('Najmanje III ili IV stepen stručne spreme elektro struke','Не ниже III или IV ступени профессионального образования по электротехническому профилю'),
 'Visoko obrazovanje iz oblasti marketinga, komunikacija, menadžmenta ili srodne oblasti': ('Visoko obrazovanje: marketing, komunikacije, menadžment ili srodna oblast','Высшее образование: маркетинг, коммуникации, менеджмент или смежная область'),
 'Master inženjer građevine, mašinstva ili arhitekture': ('Master inženjer građevine, mašinstva ili arhitekture','Магистр в области строительства, машиностроения или архитектуры'),
 'Master inženjer konstruktivnog smera': ('Master inženjer konstruktivnog smera','Магистр инженерного направления по строительным конструкциям'),
 'Master inženjer elektrotehnike i računarstva': ('Master inženjer elektrotehnike i računarstva','Магистр электротехники и вычислительной техники'),
 'Master inženjer elektrotehnike – elektroenergetske instalacije niskog i srednjeg napona': ('Master inženjer elektrotehnike — elektroenergetske instalacije niskog i srednjeg napona','Магистр электротехники — электроустановки низкого и среднего напряжения'),
 'Master inženjer mašinstva: termotehnike, termoenergetike, procesne tehnike': ('Master inženjer mašinstva: termotehnika, termoenergetika, procesna tehnika','Магистр машиностроения: теплотехника, теплоэнергетика, технологическое оборудование'),
 'Minimum VII stepen stručne spreme - pravne struke, diplomirani pravnik': ('Najmanje VII stepen stručne spreme, pravna struka — diplomirani pravnik','Не ниже VII ступени профессионального образования по юридическому профилю — дипломированный юрист'),
 'Undergraduate degree in Computer Science/Engineering and/or equivalent experience.': ('Osnovne akademske studije računarstva/inženjerstva i/ili ekvivalentno iskustvo','Диплом базового высшего образования в области компьютерных наук/инженерии и/или эквивалентный опыт'),
 'Completed vocational training, apprenticeship, degree, or comparable qualification in Information Technology, Computer Science, Software Development, or a related field': ('Završeno stručno obrazovanje, obuka kroz rad, studije ili uporediva kvalifikacija iz IT-a, računarstva, razvoja softvera ili srodne oblasti','Завершённое профессиональное обучение, ученичество, высшее образование или сопоставимая квалификация в IT, компьютерных науках, разработке ПО или смежной области'),
 'Completed vocational training, apprenticeship, or comparable qualification in Information Technology or a related field': ('Završeno stručno obrazovanje, obuka kroz rad ili uporediva kvalifikacija iz IT-a ili srodne oblasti','Завершённое профессиональное обучение, ученичество или сопоставимая квалификация в IT или смежной области'),
 'Degree in Information Technology, Computer Science, Engineering, vocational IT training or a comparable qualification': ('Diploma iz IT-a, računarstva ili inženjerstva, stručno IT obrazovanje ili uporediva kvalifikacija','Диплом в области IT, компьютерных наук или инженерии, профессиональное IT-образование либо сопоставимая квалификация'),
}

LANGUAGES = {'en':('Engleski','Английский'),'sr':('Srpski','Сербский'),'de':('Nemački','Немецкий'),
 'ru':('Ruski','Русский'),'fr':('Francuski','Французский'),'it':('Italijanski','Итальянский'),'es':('Španski','Испанский')}
LEVELS = {'napredno':('napredni nivo','продвинутый уровень'),'osnovno':('osnovni nivo','базовый уровень'),'osnovnom konverzacijskom':('osnovni konverzacijski nivo','базовый разговорный уровень'),
 'odlično':('odlično znanje','отличное знание'),'good':('dobro znanje','хорошее знание'),'fluent':('tečno','свободное владение'),
 'basic':('osnovni nivo','базовый уровень'),'native':('maternji nivo','уровень родного языка'),'excellent':('odlično znanje','отличное знание')}
OBLIGATIONS = {'REQUIRED':('obavezno','обязательно'),'PREFERRED':('poželjno','желательно'),
 'NOT_REQUIRED':('nije obavezno','не обязательно'),'UNKNOWN':('obaveznost nije navedena','обязательность не уточнена')}


def translate(table, value, lang):
    if value not in table:
        from telegram_bot.automatic_translation import resolver, TranslationUnavailable
        kind=next((name for name,t in (('title',TITLES),('education',EDUCATION),('level',LEVELS)) if table is t),None)
        if kind and resolver.get() and isinstance(value,str):
            try:
                return resolver.get()(kind,value,lang)
            except TranslationUnavailable:
                pass
        raise TranslationRequired('Translation required: '+str(value))
    return table[value][0 if lang=='sr' else 1]


def money(value):
    return format(Decimal(value),',.2f').rstrip('0').rstrip('.').replace(',','\u202f').replace('.',',')


def field_text(fields, key, lang):
    i=0 if lang=='sr' else 1
    item=(fields or {}).get(key) or {}
    if item.get('status')=='REVIEW':
        return ('potrebno je pojašnjenje','требует уточнения')[i]
    value=item.get('value') if item.get('status')=='KNOWN' else None
    if not value:
        return {'salary':('nije navedena','не указана'),'languages':('nije navedeno','не указано'),
                'education':('nije navedeno','не указано'),'work_mode':('nije naveden','не указан')}[key][i]
    if key=='work_mode':
        return translate({'OFFICE':('rad u kancelariji','работа в офисе'),'REMOTE':('rad na daljinu','удалённая работа'),'HYBRID':('hibridni rad','гибридная работа')},value,lang)
    if key=='salary':
        low,high=value.get('min'),value.get('max')
        if low is None and high is None:
            return ('nije navedena','не указана')[i]
        text=(money(low) if Decimal(low)==Decimal(high) else money(low)+'–'+money(high)) if low is not None and high is not None else ((('od ','от ')[i]+money(low)) if low is not None else (('do ','до ')[i]+money(high)))
        text+=' '+(value.get('currency') or ('(valuta nije navedena)','(валюта не указана)')[i])
        period={'MONTH':('mesečno','в месяц'),'HOUR':('po satu','в час'),'DAY':('dnevno','в день'),'YEAR':('godišnje','в год'),None:('(period nije naveden)','(период не указан)')}
        basis={'NET':('neto','нетто'),'GROSS':('bruto','брутто'),None:('neto/bruto nije navedeno','нетто/брутто не указано')}
        return text+' '+translate(period,value.get('period'),lang)+', '+translate(basis,value.get('basis'),lang)
    if key=='languages':
        lines=[]
        for entry in value:
            level=entry.get('level')
            if not level and entry.get('level_original'):
                level=translate(LEVELS,entry['level_original'].casefold(),lang)
            text=translate(LANGUAGES,entry['language'],lang)+' — '+(level or ('nije navedeno','не указано')[i])
            if text not in lines: lines.append(text)
        return '; '.join(lines)
    if key=='education':
        lines=[]
        for entry in value:
            text=translate(EDUCATION,entry['statement'],lang)
            if entry.get('bound'):
                bound={'min':('min. ','мин. '),'max':('maks. ','макс. ')}
                text=translate(bound,entry['bound'],lang)+text
            elif entry.get('requirement') in ('PREFERRED','NOT_REQUIRED'):
                text+=' ('+translate(OBLIGATIONS,entry['requirement'],lang)+')'
            if text not in lines: lines.append(text)
        return '; '.join(lines)
    raise ValueError('Unexpected field')
