import csv
import json
from pathlib import Path

from bs4 import BeautifulSoup
from peewee import IntegrityError

from helper import convert_roman_to_num, extract_input
from models.models import PDChuDe, PDChuong, PDDeMuc, PDDieu, PDFile, PDMucLienQuan, PDTable, db


BASE_DIR = Path(__file__).resolve().parent
PHAP_DIEN_DIR = BASE_DIR / "phap-dien"
DEMUC_DIR = PHAP_DIEN_DIR / "demuc"
CORPUS_DIR = (BASE_DIR.parent / "backend" / "rag" / "corpus").resolve()
CHECKPOINT = ""
RESET_DB = False


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def ensure_schema():
    models = [PDChuDe, PDDeMuc, PDChuong, PDDieu, PDTable, PDFile, PDMucLienQuan]
    db.connect(reuse_if_open=True)
    if RESET_DB:
        db.drop_tables(list(reversed(models)), safe=True)
    db.create_tables(models, safe=True)


def upsert_chu_de(chudes):
    for chude in chudes:
        PDChuDe.get_or_create(
            id=chude["Value"],
            defaults={"ten": chude["Text"], "stt": chude["STT"]},
        )


def upsert_de_muc(demucs):
    demuc_to_chude = {}
    for demuc in demucs:
        demuc_to_chude[demuc["Value"]] = demuc["ChuDe"]
        PDDeMuc.get_or_create(
            id=demuc["Value"],
            defaults={
                "ten": demuc["Text"],
                "stt": demuc["STT"],
                "chude_id": demuc["ChuDe"],
            },
        )
    return demuc_to_chude


def clean_text(value):
    return " ".join(str(value or "").split())


def read_article_body(noidung_html):
    noidung = []
    tables = []
    if not noidung_html:
        return "", tables

    for content in noidung_html.contents:
        if getattr(content, "name", None) == "table":
            tables.append(str(content))
            continue
        text = clean_text(content.get_text(" ", strip=True) if hasattr(content, "get_text") else content)
        if text:
            noidung.append(text)

    return "\n".join(noidung) + ("\n" if noidung else ""), tables


def create_chuong(chuong, demuc_id):
    mapc = chuong["MAPC"]
    instance, _ = PDChuong.get_or_create(
        mapc=mapc,
        defaults={
            "ten": chuong["TEN"],
            "chimuc": chuong["ChiMuc"],
            "stt": convert_roman_to_num(chuong["ChiMuc"]),
            "demuc_id": demuc_id,
        },
    )
    return instance


def create_fake_chuong(demuc_id):
    mapc = f"{demuc_id}-default"
    instance, _ = PDChuong.get_or_create(
        mapc=mapc,
        defaults={
            "ten": "",
            "chimuc": "0",
            "stt": 0,
            "demuc_id": demuc_id,
        },
    )
    return instance


def resolve_chuong_id(dieu, chuongs):
    if len(chuongs) == 1:
        return chuongs[0].mapc

    for chuong in chuongs:
        if dieu["MAPC"].startswith(chuong.mapc):
            return chuong.mapc

    return chuongs[0].mapc


def crawl_demuc_file(file_path, tree_nodes):
    demuc_id = file_path.stem
    demuc_html = BeautifulSoup(file_path.read_text(encoding="utf-8"), "html.parser")
    demuc_nodes = [node for node in tree_nodes if node["DeMucID"] == demuc_id]

    if not demuc_nodes:
        print(f"Khong tim thay node cho de muc {file_path.name}")
        return []

    chuong_nodes = [node for node in demuc_nodes if node["TEN"].startswith("Chương ")]
    chuongs = [create_chuong(chuong, demuc_id) for chuong in chuong_nodes]

    if not chuongs:
        chuongs = [create_fake_chuong(demuc_id)]

    dieus_lienquan = []
    dieu_nodes = [node for node in demuc_nodes if node not in chuong_nodes]

    print(f"De muc {file_path.name}: {len(chuong_nodes)} chuong, {len(dieu_nodes)} dieu")

    for dieu in dieu_nodes:
        mapc = dieu["MAPC"]
        anchor = demuc_html.select_one(f'a[name="{mapc}"]')
        if not anchor:
            print(f"Khong tim thay anchor {mapc}")
            continue

        ten = clean_text(anchor.next_sibling)
        noidung_html = anchor.parent.find_next("p", {"class": "pNoiDung"})
        noidung, tables = read_article_body(noidung_html)
        chuong_id = resolve_chuong_id(dieu, chuongs)

        try:
            PDDieu.create(
                id=mapc,
                title=ten,
                content=noidung,
                demuc_id=demuc_id,
                chuong_id=chuong_id,
            )
        except IntegrityError:
            continue

        for table in tables:
            PDTable.get_or_create(dieu_id=mapc, html=table)

        element = noidung_html.next_sibling if noidung_html else None
        while element and getattr(element, "name", None) == "a":
            link = element.get("href")
            if link:
                PDFile.get_or_create(dieu_id=mapc, link=link, defaults={"path": ""})
            element = element.next_sibling

        if element and getattr(element, "name", None) == "p" and "pChiDan" in element.get("class", []):
            for lienquan_html in element.select("a"):
                onclick = lienquan_html.get("onclick")
                mapc_lienquan = extract_input(onclick).replace("'", "") if onclick else None
                if mapc_lienquan:
                    dieus_lienquan.append({"dieu_id1": mapc, "dieu_id2": mapc_lienquan})

    return dieus_lienquan


def insert_lienquan(dieus_lienquan):
    for lienquan in dieus_lienquan:
        try:
            PDMucLienQuan.get_or_create(
                dieu_id1=lienquan["dieu_id1"],
                dieu_id2=lienquan["dieu_id2"],
            )
        except IntegrityError:
            print(f"Khong the insert lien quan {lienquan['dieu_id1']} - {lienquan['dieu_id2']}")


def export_pddieu_corpus():
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CORPUS_DIR / "pddieu.csv"

    query = (
        PDDieu.select(PDDieu.id, PDDieu.title, PDDieu.content, PDDieu.demuc_id, PDDieu.chuong_id)
        .order_by(PDDieu.demuc_id, PDDieu.chuong_id, PDDieu.id)
    )

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["id", "title", "content", "demuc_id", "chuong_id"])
        for dieu in query:
            writer.writerow([dieu.id, dieu.title, dieu.content, dieu.demuc_id_id, dieu.chuong_id_id])

    print(f"Exported {output_path}")


def should_skip(file_name, skipping):
    if not CHECKPOINT:
        return False, False
    if file_name == CHECKPOINT:
        return False, False
    return skipping, skipping


def main():
    ensure_schema()
    chudes = load_json(PHAP_DIEN_DIR / "chude.json")
    demucs = load_json(PHAP_DIEN_DIR / "demuc.json")
    tree_nodes = load_json(PHAP_DIEN_DIR / "treeNode.json")

    upsert_chu_de(chudes)
    demuc_to_chude = upsert_de_muc(demucs)

    all_dieus_lienquan = []
    skipping = bool(CHECKPOINT)

    for file_path in sorted(DEMUC_DIR.glob("*.html")):
        skip, skipping = should_skip(file_path.name, skipping)
        if skip:
            continue
        all_dieus_lienquan.extend(crawl_demuc_file(file_path, tree_nodes))

    insert_lienquan(all_dieus_lienquan)
    export_pddieu_corpus()


if __name__ == "__main__":
    main()
