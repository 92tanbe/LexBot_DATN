import os
import re
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
IS_DOCKER = Path("/.dockerenv").exists()
DB_NAME = "law"
DB_USER = "root"
DB_PASSWORD = os.getenv("MYSQL_PASSWORD")
DB_HOST = "law-mysql" if IS_DOCKER else "127.0.0.1"
DB_PORT = 3306
ENGINE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
engine = create_engine(ENGINE_URL)


def get_item_id(url):
    if pd.isna(url):
        return None
    match = re.search(r"ItemID=(\d+)", str(url))
    return match.group(1) if match else None


def ensure_schema():
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS vbpl ("
                "id VARCHAR(32) PRIMARY KEY, "
                "noidung LONGTEXT NOT NULL"
                ") CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


def existing_ids():
    ensure_schema()
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id FROM vbpl")).fetchall()
    return {str(row[0]) for row in rows}


def fetch_document(item_id):
    url = f"https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID={item_id}"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    div_text = soup.find("div", class_="fulltext")
    if not div_text:
        return None
    divs = div_text.find_all("div")
    return str(divs[1] if len(divs) > 1 else div_text)


def save_data(records):
    if not records:
        return

    with engine.begin() as connection:
        for record in records:
            connection.execute(
                text("INSERT IGNORE INTO vbpl (id, noidung) VALUES (:id, :noidung)"),
                record,
            )


def main():
    source = pd.read_sql(
        "SELECT DISTINCT vbqppl_link FROM pddieu WHERE vbqppl_link IS NOT NULL AND vbqppl_link <> ''",
        con=engine,
    )
    ids = source["vbqppl_link"].map(get_item_id).dropna().drop_duplicates().tolist()
    crawled = existing_ids()
    records = []

    for index, item_id in enumerate(ids, start=1):
        if item_id in crawled:
            continue

        print(f"{index}/{len(ids)} Get data id {item_id}")
        try:
            noidung = fetch_document(item_id)
        except Exception as error:
            print(f"Skip {item_id}: {error}")
            continue

        if not noidung:
            continue

        records.append({"id": item_id, "noidung": noidung})
        if len(records) >= 10:
            save_data(records)
            records.clear()

    save_data(records)


if __name__ == "__main__":
    main()
