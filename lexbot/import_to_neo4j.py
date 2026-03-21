#!/usr/bin/env python3
"""
import_to_neo4j.py
─────────────────────────────────────────────────────────
Import dữ liệu luật từ 2 CSV vào Neo4j (local hoặc AuraDB)

Cách dùng:
  pip install neo4j pandas
  python import_to_neo4j.py

Biến môi trường (hoặc điền trực tiếp):
  NEO4J_URI      bolt://localhost:7687  (local)
                 neo4j+s://xxxx.databases.neo4j.io  (AuraDB)
  NEO4J_USER     neo4j
  NEO4J_PASSWORD your_password
"""

import os, json, time
from pathlib import Path
import pandas as pd
from neo4j import GraphDatabase

# ── Cấu hình ────────────────────────────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "password")

# Đường dẫn file CSV (thay đổi nếu cần)
CSV_FILES = {
    "blhs_2025": "blhs_2025_from_text.csv",
    "giaothong": "giaothong.csv",
}
SOURCE_LABELS = {
    "blhs_2025": "Bộ luật Hình sự 2025",
    "giaothong": "Nghị định Giao thông",
}


# ── Build Graph Data ─────────────────────────────────────────────
def build_graph(csv_files: dict) -> dict:
    nodes = {k: {} for k in ("LuatBan","Phan","Chuong","Dieu","Khoan","Diem")}
    rels  = []

    def sid(s): return str(s).strip().replace(" ","_")[:60]

    for src, fpath in csv_files.items():
        if not Path(fpath).exists():
            print(f"  ⚠️  Không tìm thấy: {fpath}")
            continue

        df = pd.read_csv(fpath, encoding="utf-8-sig").fillna("")
        label = SOURCE_LABELS[src]
        print(f"  📄 {fpath}: {len(df)} rows")

        lb_id = f"luatban_{src}"
        nodes["LuatBan"][lb_id] = {"id": lb_id, "ten": label, "ma": src}

        for _, row in df.iterrows():
            phan_txt   = str(row.get("Phần","")).strip()
            chuong_txt = str(row.get("Chương","")).strip()
            so_dieu    = str(row.get("Số điều","")).strip()
            tieu_de    = str(row.get("Tiêu đề điều","")).strip()
            nd_dieu    = str(row.get("Nội dung điều","")).strip()
            so_khoan   = str(row.get("Số khoản","")).strip()
            nd_khoan   = str(row.get("Nội dung khoản","")).strip()
            diem       = str(row.get("Điểm","")).strip()
            nd_diem    = str(row.get("Nội dung điểm","")).strip()

            if not so_dieu: continue

            phan_id   = f"phan_{src}_{sid(phan_txt)}"
            chuong_id = f"chuong_{src}_{sid(chuong_txt)}"
            dieu_id   = f"dieu_{src}_{so_dieu}"

            if phan_id not in nodes["Phan"]:
                nodes["Phan"][phan_id] = {"id": phan_id, "ten": phan_txt, "source": src}
                rels.append({"f": lb_id,    "t": phan_id,   "type": "CO_PHAN"})

            if chuong_id not in nodes["Chuong"]:
                nodes["Chuong"][chuong_id] = {"id": chuong_id, "ten": chuong_txt, "source": src}
                rels.append({"f": phan_id,   "t": chuong_id, "type": "CO_CHUONG"})

            if dieu_id not in nodes["Dieu"]:
                nodes["Dieu"][dieu_id] = {
                    "id": dieu_id, "so_dieu": so_dieu,
                    "tieu_de": tieu_de, "noi_dung": nd_dieu,
                    "source": src, "luat": label,
                }
                rels.append({"f": chuong_id, "t": dieu_id,   "type": "CO_DIEU"})

            if so_khoan:
                khoan_id = f"khoan_{src}_{so_dieu}_{so_khoan}"
                if khoan_id not in nodes["Khoan"]:
                    nodes["Khoan"][khoan_id] = {
                        "id": khoan_id, "so_khoan": so_khoan,
                        "noi_dung": nd_khoan, "source": src,
                    }
                    rels.append({"f": dieu_id, "t": khoan_id, "type": "CO_KHOAN"})

                if diem:
                    diem_id = f"diem_{src}_{so_dieu}_{so_khoan}_{diem}"
                    if diem_id not in nodes["Diem"]:
                        nodes["Diem"][diem_id] = {
                            "id": diem_id, "diem": diem,
                            "noi_dung": nd_diem, "source": src,
                        }
                        rels.append({"f": khoan_id, "t": diem_id, "type": "CO_DIEM"})

    return {"nodes": nodes, "rels": rels}


# ── Neo4j Import ─────────────────────────────────────────────────
def create_schema(session):
    """Tạo constraints & indexes."""
    constraints = [
        ("luatban_id", "LuatBan"),("phan_id","Phan"),("chuong_id","Chuong"),
        ("dieu_id","Dieu"),("khoan_id","Khoan"),("diem_id","Diem"),
    ]
    for name, label in constraints:
        session.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.id IS UNIQUE")

    indexes = [
        "CREATE INDEX dieu_so     IF NOT EXISTS FOR (n:Dieu)  ON (n.so_dieu)",
        "CREATE INDEX dieu_source IF NOT EXISTS FOR (n:Dieu)  ON (n.source)",
        "CREATE INDEX khoan_src   IF NOT EXISTS FOR (n:Khoan) ON (n.source)",
    ]
    for q in indexes:
        try: session.run(q)
        except: pass

    try:
        session.run(
            "CREATE FULLTEXT INDEX lawFulltext IF NOT EXISTS "
            "FOR (n:Dieu|Khoan|Diem) ON EACH [n.tieu_de, n.noi_dung]"
        )
    except Exception as e:
        print(f"    Fulltext index: {e}")

    print("  ✅ Schema OK")


def batch_merge_nodes(session, label: str, node_list: list, props: list):
    set_clause = ", ".join(f"n.{p} = row.{p}" for p in props)
    q = f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET {set_clause}"
    total = 0
    for i in range(0, len(node_list), 300):
        session.run(q, rows=node_list[i:i+300])
        total += min(300, len(node_list)-i)
    print(f"    {label:10s}: {total:,} nodes")


REL_LABELS = {
    "CO_PHAN"  : ("LuatBan","Phan"),
    "CO_CHUONG": ("Phan",   "Chuong"),
    "CO_DIEU"  : ("Chuong", "Dieu"),
    "CO_KHOAN" : ("Dieu",   "Khoan"),
    "CO_DIEM"  : ("Khoan",  "Diem"),
}

def batch_merge_rels(session, rel_type: str, rel_list: list):
    fa, ta = REL_LABELS[rel_type]
    q = (f"UNWIND $rows AS row "
         f"MATCH (a:{fa} {{id: row.f}}), (b:{ta} {{id: row.t}}) "
         f"MERGE (a)-[:{rel_type}]->(b)")
    total = 0
    for i in range(0, len(rel_list), 500):
        chunk = [{"f": r["f"], "t": r["t"]} for r in rel_list[i:i+500]]
        session.run(q, rows=chunk)
        total += len(chunk)
    print(f"    {rel_type:15s}: {total:,} rels")


def import_to_neo4j(graph_data: dict):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    with driver.session() as s:
        s.run("RETURN 1")
    print(f"✅ Kết nối Neo4j: {NEO4J_URI}")

    nodes = graph_data["nodes"]
    rels  = graph_data["rels"]

    print("\nTạo schema...")
    with driver.session() as s:
        create_schema(s)

    print("\nImport nodes...")
    with driver.session() as s:
        batch_merge_nodes(s, "LuatBan", list(nodes["LuatBan"].values()), ["ten","ma"])
        batch_merge_nodes(s, "Phan",    list(nodes["Phan"].values()),    ["ten","source"])
        batch_merge_nodes(s, "Chuong",  list(nodes["Chuong"].values()),  ["ten","source"])
        batch_merge_nodes(s, "Dieu",    list(nodes["Dieu"].values()),    ["so_dieu","tieu_de","noi_dung","source","luat"])
        batch_merge_nodes(s, "Khoan",   list(nodes["Khoan"].values()),   ["so_khoan","noi_dung","source"])
        batch_merge_nodes(s, "Diem",    list(nodes["Diem"].values()),    ["diem","noi_dung","source"])

    print("\nImport relationships...")
    from collections import defaultdict
    by_type = defaultdict(list)
    for r in rels:
        by_type[r["type"]].append(r)

    with driver.session() as s:
        for rel_type in ["CO_PHAN","CO_CHUONG","CO_DIEU","CO_KHOAN","CO_DIEM"]:
            if rel_type in by_type:
                batch_merge_rels(s, rel_type, by_type[rel_type])

    # Stats
    print("\nGraph statistics:")
    with driver.session() as s:
        result = s.run("MATCH (n) RETURN labels(n)[0] AS lbl, count(n) AS cnt ORDER BY cnt DESC")
        for r in result:
            print(f"  {r['lbl']:12s}: {r['cnt']:,}")
        result2 = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
        print(f"  {'TOTAL RELS':12s}: {result2.single()['cnt']:,}")

    driver.close()
    print("\n🎉 Import hoàn tất!")


# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Lexbot Neo4j Import ===\n")
    print("Đọc & xây dựng graph data...")
    t0 = time.time()
    graph_data = build_graph(CSV_FILES)
    total_nodes = sum(len(v) for v in graph_data["nodes"].values())
    print(f"  Tổng: {total_nodes:,} nodes, {len(graph_data['rels']):,} rels ({time.time()-t0:.1f}s)")
    print()
    import_to_neo4j(graph_data)
