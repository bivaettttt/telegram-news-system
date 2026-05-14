"""
legal_compliance.py — соответствие российскому законодательству для Telegram-канала.

Согласно ФЗ «О контроле за деятельностью лиц, находящихся под иностранным влиянием»
(№ 255-ФЗ от 14.07.2022), при упоминании иностранных агентов необходимо указывать
соответствующий статус.

Законодательные основания:
- ФЗ от 14.07.2022 № 255-ФЗ — иностранные агенты
- ФЗ от 28.12.2012 № 272-ФЗ — нежелательные организации
- Решения Верховного суда РФ — террористические организации

ВАЖНО: Список обновляется. Реестр Минюста: https://minjust.gov.ru/ru/pages/reestr-inostryannykh-agentov/
По состоянию на март 2026 года.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Иностранные агенты — СМИ и организации, часто упоминаемые в новостях
# Источник: Реестр Минюста РФ
# ---------------------------------------------------------------------------
INOAGENTS: list[tuple[list[str], str]] = [
    # (список паттернов для поиска, метка)
    (["медуза", "meduza.io", "meduza"], "Медуза*"),
    (["дождь", "tv rain", "tvrain", "дождь*"], "ТВ Дождь*"),
    (["медиазона", "mediazona"], "Медиазона*"),
    (["important stories", "important.stories", "истории", "истории*", "iстории"], "iStories*"),
    (["the insider", "инсайдер"], "The Insider*"),
    (["новая газета европа", "novayagazeta.eu"], "Новая газета Европа*"),
    (["русская служба бbc", "bbc russia", "bbc русская"], "BBC Русская служба*"),
    (["радио свобода", "radio svoboda", "rferl"], "Радио Свобода*"),
    (["bellingcat", "беллингкет"], "Bellingcat*"),
    (["мемориал", "memorial"], "Мемориал*"),
    (["ovd-info", "овд-инфо", "ovdinfo"], "ОВД-Инфо*"),
    (["гласная"], "Гласная*"),
    (["дw", "deutsche welle russia", "немецкая волна"], "Deutsche Welle*"),
    (["настоящее время", "current time tv"], "Настоящее Время*"),
    (["медианяня"], "МедиаНяня*"),
    (["русьская реальность", "russkaya realnost"], "Русская Реальность*"),
]

# ---------------------------------------------------------------------------
# Нежелательные организации
# ---------------------------------------------------------------------------
UNWANTED_ORGS: list[tuple[list[str], str]] = [
    (["oas", "организация американских государств"], "ОАГ†"),
    (["national endowment for democracy", "ned ", "национальный фонд демократии"], "NED†"),
    (["открытое общество", "open society", "фонд сороса", "sorosfoundation"], "Фонд «Открытое общество»†"),
    (["usaid", "юсаид", "агентство сша по международному развитию"], "USAID†"),
    (["british council"], "British Council†"),
    (["amnesty international", "международная амнистия"], "Amnesty International†"),
]

# ---------------------------------------------------------------------------
# Террористические и запрещённые организации
# ---------------------------------------------------------------------------
BANNED_ORGS: list[tuple[list[str], str]] = [
    (["игил", "isil", "isis", "islamic state", "исламское государство", "даиш", "daesh"], "ИГИЛ‡"),
    (["аль-каида", "al-qaeda", "аль каида", "al qaeda"], "Аль-Каида‡"),
    (["правый сектор", "pravy sektor", "right sector"], "Правый сектор‡"),
    (["азов", "полк азов", "батальон азов", "azov"], "Азов‡"),
    (["хизб ут-тахрир", "hizb ut-tahrir"], "Хизб ут-Тахрир‡"),
    (["свидетели иеговы", "jehovah", "iehovah"], "Свидетели Иеговы‡"),
    (["ана-унсо", "уна-унсо", "una-unso"], "УНА-УНСО‡"),
    (["организация братья-мусульмане", "muslim brotherhood", "братья-мусульмане"], "Братья-мусульмане‡"),
    (["боко харам", "boko haram"], "Боко Харам‡"),
    (["аум синрике", "aum shinrikyo"], "Аум Синрикё‡"),
    (["ккк", "ky klux klan", "ku klux klan"], "ККК‡"),
    (["нацбол", "нбп", "национал-большевик"], "НБП‡"),
    (["ан-нусра", "al-nusra", "jabhat al-nusra"], "Джабхат ан-Нусра‡"),
]

# ---------------------------------------------------------------------------
# Footnote texts
# ---------------------------------------------------------------------------
FOOTNOTE_INOAGENT = "* — признан(а) иностранным агентом по законодательству РФ"
FOOTNOTE_UNWANTED = "† — признан(а) нежелательной организацией в РФ"
FOOTNOTE_BANNED = "‡ — запрещённая организация в РФ (решение суда)"


def _norm(text: str) -> str:
    return text.lower().strip()


class LegalCheckResult:
    def __init__(self) -> None:
        self.has_inoagent: bool = False
        self.has_unwanted: bool = False
        self.has_banned: bool = False
        self.found_inoagents: list[str] = []
        self.found_unwanted: list[str] = []
        self.found_banned: list[str] = []

    @property
    def needs_footnote(self) -> bool:
        return self.has_inoagent or self.has_unwanted or self.has_banned

    def get_footnotes(self) -> list[str]:
        notes = []
        if self.has_inoagent:
            notes.append(FOOTNOTE_INOAGENT)
        if self.has_unwanted:
            notes.append(FOOTNOTE_UNWANTED)
        if self.has_banned:
            notes.append(FOOTNOTE_BANNED)
        return notes


def check_legal_compliance(title: str | None, summary: str | None) -> LegalCheckResult:
    """
    Проверяет текст поста на упоминания иноагентов и запрещённых организаций.
    Возвращает LegalCheckResult с флагами и списками найденных организаций.
    """
    result = LegalCheckResult()
    blob = _norm((title or "") + " " + (summary or ""))

    if not blob.strip():
        return result

    for patterns, label in INOAGENTS:
        if any(p in blob for p in patterns):
            result.has_inoagent = True
            if label not in result.found_inoagents:
                result.found_inoagents.append(label)

    for patterns, label in UNWANTED_ORGS:
        if any(p in blob for p in patterns):
            result.has_unwanted = True
            if label not in result.found_unwanted:
                result.found_unwanted.append(label)

    for patterns, label in BANNED_ORGS:
        if any(p in blob for p in patterns):
            result.has_banned = True
            if label not in result.found_banned:
                result.found_banned.append(label)

    return result
