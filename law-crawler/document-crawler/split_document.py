import os
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")
IS_DOCKER = Path("/.dockerenv").exists()
DB_NAME = "law"
DB_USER = "root"
DB_PASSWORD = os.getenv("MYSQL_PASSWORD")
DB_HOST = "law-mysql" if IS_DOCKER else "127.0.0.1"
DB_PORT = 3306
ENGINE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
engine = create_engine(ENGINE_URL)


def ensure_schema():
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS vb_chimuc ("
                "id INT PRIMARY KEY, "
                "id_vb VARCHAR(32) NOT NULL, "
                "chi_muc_cha INT NULL, "
                "content LONGTEXT NOT NULL"
                ") CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        for statement in (
            "ALTER TABLE vb_chimuc ADD COLUMN content LONGTEXT NULL",
            "UPDATE vb_chimuc SET content = noi_dung WHERE content IS NULL",
        ):
            try:
                connection.execute(text(statement))
            except Exception:
                pass


def next_id():
    with engine.begin() as connection:
        value = connection.execute(text("SELECT COALESCE(MAX(id), 0) FROM vb_chimuc")).scalar()
    return int(value) + 1


def existing_document_ids():
    ensure_schema()
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT DISTINCT id_vb FROM vb_chimuc")).fetchall()
    return {str(row[0]) for row in rows}


def normalize_text(text):
    return " ".join(str(text or "").replace("\n", " ").split())


def split_document(id_vb, html, start_id):
    soup = BeautifulSoup(html or "", "html.parser").find("div", id="toanvancontent")
    if not soup:
        return [], start_id

    texts = [normalize_text(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
    texts = [text for text in texts if text]
    rows = []
    current_id = start_id
    current_parent_id = None
    current_type = None
    buffer = []

    def flush():
        if not buffer or current_type is None:
            return
        rows.append(
            {
                "id": current_id,
                "id_vb": id_vb,
                "chi_muc_cha": None if current_type == "chapter" else current_parent_id,
                "content": "\n".join(buffer) + "\n",
            }
        )

    for text in texts:
        is_chapter = text.startswith("Chương") or text.startswith("CHƯƠNG")
        is_article = text.startswith("Điều") or text.startswith("ĐIỀU")

        if is_chapter or is_article:
            flush()
            if buffer:
                current_id += 1
            buffer = []

            if is_chapter:
                current_type = "chapter"
                current_parent_id = current_id
            else:
                current_type = "article"

        if current_type:
            buffer.append(text)

    flush()
    return rows, current_id + 1 if buffer else current_id


def save_rows(rows):
    if not rows:
        return

    with engine.begin() as connection:
        for row in rows:
            connection.execute(
                text(
                    "INSERT IGNORE INTO vb_chimuc (id, id_vb, chi_muc_cha, content) "
                    "VALUES (:id, :id_vb, :chi_muc_cha, :content)"
                ),
                row,
            )


def main():
    ensure_schema()
    documents = pd.read_sql("SELECT id, noidung FROM vbpl ORDER BY id", con=engine)
    processed_ids = existing_document_ids()
    current_id = next_id()
    batch = []

    for _, document in documents.iterrows():
        id_vb = str(document["id"])
        if id_vb in processed_ids:
            continue

        rows, current_id = split_document(id_vb, document["noidung"], current_id)
        batch.extend(rows)

        if len(batch) >= 500:
            save_rows(batch)
            batch.clear()

    save_rows(batch)


if __name__ == "__main__":
    main()
