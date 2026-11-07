import pandas as pd

games = [
    ["Cyberpunk 2077", "CD PROJEKT RED", "2020-12-10"],
    ["Hogwarts Legacy", "Warner Bros. Games", "2023-02-10"],
    ["Starfield", "Bethesda Softworks", "2023-09-06"],
    ["Assassin's Creed Shadows", "Ubisoft", "2025-03-20"],
    ["Red Dead Redemption 2", "Rockstar Games", "2018-10-26"],
    ["Grand Theft Auto V", "Rockstar Games", "2013-09-17"],
    ["The Witcher 3: Wild Hunt", "CD PROJEKT RED", "2015-05-19"],
    ["ELDEN RING", "Bandai Namco Entertainment", "2022-02-25"],
    ["Ghost of Tsushima", "Sony Interactive Entertainment", "2020-07-17"],
    ["Marvel's Spider-Man 2", "Sony Interactive Entertainment", "2023-10-20"],
    ["Resident Evil 4", "Capcom", "2023-03-24"],
    ["Monster Hunter Wilds", "Capcom", "2025-02-28"],
    ["Final Fantasy XVI", "Square Enix", "2023-06-22"],
    ["Final Fantasy VII Rebirth", "Square Enix", "2024-02-29"],
    ["Assassin's Creed Valhalla", "Ubisoft", "2020-11-10"],
    ["Far Cry 6", "Ubisoft", "2021-10-07"],
    ["Avatar: Frontiers of Pandora", "Ubisoft", "2023-12-07"],
    ["Forza Horizon 5", "Xbox Game Studios", "2021-11-09"],
    ["Diablo IV", "Blizzard Entertainment", "2023-06-05"],
    ["DOOM Eternal", "Bethesda Softworks", "2020-03-20"],
    ["Horizon Forbidden West", "Sony Interactive Entertainment", "2022-02-18"],
    ["God of War", "Sony Interactive Entertainment", "2018-04-20"],
    ["Horizon Zero Dawn", "Sony Interactive Entertainment", "2017-02-28"],
    ["Persona 3 Reload", "Atlus", "2024-02-02"],
    ["Like a Dragon: Infinite Wealth", "Sega", "2024-01-26"],
]

df = pd.DataFrame(games, columns=["game_name", "publisher_name", "release_date"])
path = r"C:\Users\aayan\GitProjects\WHACK2026\data\games.csv"
df.to_csv(path, index=False, encoding="utf-8-sig")
print(f"Created {path} with {len(df)} games and exactly 3 columns.")
