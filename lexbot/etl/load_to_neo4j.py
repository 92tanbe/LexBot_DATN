# =============================================================================
# etl/load_to_neo4j.py
# Đọc 2 file CSV và import vào Neo4j Graph Database
# =============================================================================

import csv
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from neo4j import GraphDatabase
from config.settings import NEO4J, DATA


class LexBotETL:
    """
    ETL Pipeline: CSV → Neo4j Graph
    
    Graph Schema được tạo ra:
    
    (:VanBanPhapLuat {ten, loai})
         |
    [:CO_CHUONG]
         ↓
    (:Chuong {ma, ten})
         |
    [:CO_DIEU]
         ↓
    (:Dieu {so, ten, noi_dung})
         |
    [:CO_KHOAN]
         ↓
    (:Khoan {so, noi_dung})
         |
    [:CO_DIEM]
         ↓
    (:Diem {ky_hieu, noi_dung})
    """

    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J.uri,
            auth=(NEO4J.username, NEO4J.password)
        )
        print(f"✅ Kết nối Neo4j: {NEO4J.uri}")

    def close(self):
        self.driver.close()

    # ------------------------------------------------------------------
    # BƯỚC 1: Tạo constraints & indexes để tối ưu query
    # ------------------------------------------------------------------
    def create_constraints(self):
        queries = [
            # Unique constraints
            "CREATE CONSTRAINT IF NOT EXISTS FOR (v:VanBanPhapLuat) REQUIRE v.ten IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dieu) REQUIRE (d.so, d.van_ban) IS UNIQUE",
            # Indexes để full-text search
            "CREATE FULLTEXT INDEX dieuFullText IF NOT EXISTS FOR (d:Dieu) ON EACH [d.ten, d.noi_dung]",
            "CREATE FULLTEXT INDEX khoanFullText IF NOT EXISTS FOR (k:Khoan) ON EACH [k.noi_dung]",
            "CREATE FULLTEXT INDEX diemFullText  IF NOT EXISTS FOR (p:Diem)  ON EACH [p.noi_dung]",
        ]
        with self.driver.session(database=NEO4J.database) as session:
            for q in queries:
                try:
                    session.run(q)
                    print(f"  ✓ {q[:60]}...")
                except Exception as e:
                    print(f"  ⚠ {e}")
        print("✅ Constraints & Indexes tạo xong\n")

    # ------------------------------------------------------------------
    # BƯỚC 2: Import BLHS 2025
    # ------------------------------------------------------------------
    def load_blhs(self):
        print("📕 Đang import BLHS 2025...")
        count = 0

        with open(DATA.blhs_csv, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            with self.driver.session(database=NEO4J.database) as session:
                for row in reader:
                    self._upsert_row(session, row, van_ban="BLHS_2025", loai="Hình sự")
                    count += 1
                    if count % 200 == 0:
                        print(f"  ... {count} dòng")

        print(f"✅ BLHS: {count} dòng import xong\n")

    # ------------------------------------------------------------------
    # BƯỚC 3: Import Nghị định Giao thông
    # ------------------------------------------------------------------
    def load_giaothong(self):
        print("🚦 Đang import Nghị định Giao thông...")
        count = 0

        with open(DATA.giaothong_csv, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            with self.driver.session(database=NEO4J.database) as session:
                for row in reader:
                    self._upsert_row(session, row, van_ban="ND_GIAOTHONG", loai="Hành chính")
                    count += 1
                    if count % 200 == 0:
                        print(f"  ... {count} dòng")

        print(f"✅ Nghị định GT: {count} dòng import xong\n")

    # ------------------------------------------------------------------
    # Core: Upsert 1 dòng CSV → graph nodes + relationships
    # ------------------------------------------------------------------
    def _upsert_row(self, session, row: dict, van_ban: str, loai: str):
        """
        Mỗi dòng CSV có thể có: Phần, Chương, Điều, Khoản, Điểm
        Ta dùng MERGE để tránh duplicate khi chạy lại.
        """
        cypher = """
        // 1. VanBanPhapLuat node
        MERGE (vb:VanBanPhapLuat {ten: $van_ban})
          ON CREATE SET vb.loai = $loai

        // 2. Chuong node
        WITH vb
        MERGE (ch:Chuong {ma: $ma_chuong, van_ban: $van_ban})
          ON CREATE SET ch.ten = $ten_chuong
        MERGE (vb)-[:CO_CHUONG]->(ch)

        // 3. Dieu node
        WITH ch, vb
        MERGE (d:Dieu {so: $so_dieu, van_ban: $van_ban})
          ON CREATE SET
            d.ten      = $ten_dieu,
            d.noi_dung = $noi_dung_dieu,
            d.loai     = $loai
        MERGE (ch)-[:CO_DIEU]->(d)

        // 4. Khoan node (nếu có)
        WITH d
        FOREACH (_ IN CASE WHEN $so_khoan IS NOT NULL THEN [1] ELSE [] END |
          MERGE (k:Khoan {so: $so_khoan, dieu_so: $so_dieu, van_ban: $van_ban})
            ON CREATE SET k.noi_dung = $noi_dung_khoan
          MERGE (d)-[:CO_KHOAN]->(k)
        )

        // 5. Diem node (nếu có)
        WITH d
        FOREACH (_ IN CASE WHEN $ky_hieu_diem IS NOT NULL THEN [1] ELSE [] END |
          MERGE (p:Diem {ky_hieu: $ky_hieu_diem, dieu_so: $so_dieu,
                         khoan_so: $so_khoan, van_ban: $van_ban})
            ON CREATE SET p.noi_dung = $noi_dung_diem
          MERGE (d)-[:CO_DIEM]->(p)
        )
        """

        def clean(val):
            return val.strip() if val and val.strip() else None

        session.run(cypher, {
            "van_ban":        van_ban,
            "loai":           loai,
            "ma_chuong":      clean(row.get("Chương", "")),
            "ten_chuong":     clean(row.get("Chương", "")),
            "so_dieu":        clean(row.get("Số điều", "")),
            "ten_dieu":       clean(row.get("Tiêu đề điều", "")),
            "noi_dung_dieu":  clean(row.get("Nội dung điều", "")),
            "so_khoan":       clean(row.get("Số khoản", "")),
            "noi_dung_khoan": clean(row.get("Nội dung khoản", "")),
            "ky_hieu_diem":   clean(row.get("Điểm", "")),
            "noi_dung_diem":  clean(row.get("Nội dung điểm", "")),
        })

    # ------------------------------------------------------------------
    # BƯỚC 4: Thêm metadata giúp RAG dễ tìm kiếm
    # ------------------------------------------------------------------
    def add_search_metadata(self):
        """Gắn nhãn loại hình phạt cho từng Điều để dễ phân loại sau"""
        print("🏷️  Đang gắn metadata tìm kiếm...")

        with self.driver.session(database=NEO4J.database) as session:
            # Gắn label :DieuHinhSu cho điều thuộc BLHS
            session.run("""
                MATCH (d:Dieu {loai: 'Hình sự'})
                SET d:DieuHinhSu
            """)
            # Gắn label :DieuHanhChinh cho điều thuộc Nghị định
            session.run("""
                MATCH (d:Dieu {loai: 'Hành chính'})
                SET d:DieuHanhChinh
            """)

        print("✅ Metadata xong\n")

    # ------------------------------------------------------------------
    # Chạy toàn bộ pipeline
    # ------------------------------------------------------------------
    def run(self):
        print("=" * 60)
        print("  LexBot ETL Pipeline")
        print("=" * 60)
        self.create_constraints()
        self.load_blhs()
        self.load_giaothong()
        self.add_search_metadata()
        self.print_stats()

    def print_stats(self):
        with self.driver.session(database=NEO4J.database) as session:
            result = session.run("""
                MATCH (n) 
                RETURN labels(n)[0] AS label, count(n) AS total
                ORDER BY total DESC
            """)
            print("\n📊 Thống kê Graph Database:")
            print("-" * 35)
            for record in result:
                print(f"  {record['label']:<20} {record['total']:>6} nodes")

            result2 = session.run("MATCH ()-[r]->() RETURN count(r) AS total")
            print(f"  {'Relationships':<20} {result2.single()['total']:>6}")
            print("-" * 35)


# ==============================================================================
if __name__ == "__main__":
    etl = LexBotETL()
    try:
        etl.run()
    finally:
        etl.close()
