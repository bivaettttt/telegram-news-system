def apply_manual_reclassification(title_ru: str | None, category: str) -> str:
    text = (title_ru or "").lower()

    overrides_to_economy = [
        "экспорт нефти",
        "нефть и газ",
        "рост банка",
        "банкнотах",
        "бюджет-2025",
        "продовольственных талонов",
        "газированных напитков",
        "мазут",
    ]

    overrides_to_world = [
        "в ереване проходят акции",
        "социальные сети попросили ужесточить",
        "иранские женщины",
        "скандал с автомобилями-призраками",
        "почему в рождество на железных дорогах",
        "реальное влияние дорожных работ",
        "у нас больше средств контроля конфиденциальности",
    ]

    overrides_to_skip = [
        "паралимпиаде",
        "слаломе",
        "прогнозы саттона",
        "шесть наций",
        "как долго продлятся холода",
        "ufc",
        "фестивалях и спортивных матчах",
        "что в мире",
    ]

    for phrase in overrides_to_economy:
        if phrase in text:
            return "economy"

    for phrase in overrides_to_world:
        if phrase in text:
            return "world"

    for phrase in overrides_to_skip:
        if phrase in text:
            return "skip"

    return category