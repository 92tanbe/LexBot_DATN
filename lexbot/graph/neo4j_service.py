# =============================================================================
# graph/neo4j_service.py
# Tất cả Cypher queries để tra cứu luật từ Neo4j
# =============================================================================

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from neo4j import GraphDatabase
from config.settings import NEO4J


class Neo4jService:
    """
    Lớp trung gian giữa chatbot và Neo4j.
    Mỗi method = 1 loại query cụ thể.
    """

    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J.uri,
            auth=(NEO4J.username, NEO4J.password)
        )

    def close(self):
        self.driver.close()

    # ---------------------------------------------------------------
    # QUERY 1: Full-text search - tìm điều luật theo từ khóa
    # ---------------------------------------------------------------
    def search_by_keyword(self, keyword: str, limit: int = 5) -> list[dict]:
        """
        Dùng Full-Text Index để tìm điều luật liên quan đến từ khóa.
        Ví dụ: keyword = "say rượu gây tai nạn"
        """
        cypher = """
        CALL db.index.fulltext.queryNodes(
            'dieuFullText', $keyword
        ) YIELD node AS d, score
        MATCH (ch:Chuong)-[:CO_DIEU]->(d)
        MATCH (vb:VanBanPhapLuat)-[:CO_CHUONG]->(ch)
        RETURN
            vb.ten        AS van_ban,
            vb.loai       AS loai_van_ban,
            d.so          AS so_dieu,
            d.ten         AS ten_dieu,
            d.noi_dung    AS noi_dung,
            ch.ten        AS chuong,
            score
        ORDER BY score DESC
        LIMIT $limit
        """
        with self.driver.session(database=NEO4J.database) as s:
            return [dict(r) for r in s.run(cypher, keyword=keyword, limit=limit)]

    # ---------------------------------------------------------------
    # QUERY 2: Lấy toàn bộ nội dung 1 Điều (gồm các Khoản, Điểm)
    # ---------------------------------------------------------------
    def get_dieu_full(self, so_dieu: str, van_ban: str) -> dict:
        """
        Lấy nội dung đầy đủ của 1 điều luật cụ thể.
        Ví dụ: so_dieu="260", van_ban="BLHS_2025"
        """
        cypher = """
        MATCH (d:Dieu {so: $so_dieu, van_ban: $van_ban})
        OPTIONAL MATCH (d)-[:CO_KHOAN]->(k:Khoan)
        OPTIONAL MATCH (d)-[:CO_DIEM]->(p:Diem)
        RETURN
            d.so       AS so_dieu,
            d.ten      AS ten_dieu,
            d.noi_dung AS noi_dung_dieu,
            d.loai     AS loai,
            collect(DISTINCT {
                so: k.so,
                noi_dung: k.noi_dung
            }) AS khoan_list,
            collect(DISTINCT {
                ky_hieu: p.ky_hieu,
                noi_dung: p.noi_dung
            }) AS diem_list
        """
        with self.driver.session(database=NEO4J.database) as s:
            result = s.run(cypher, so_dieu=so_dieu, van_ban=van_ban)
            record = result.single()
            return dict(record) if record else {}

    # ---------------------------------------------------------------
    # QUERY 3: Tìm điều luật hình sự liên quan đến hậu quả
    # ---------------------------------------------------------------
    def search_hinh_su_by_hau_qua(self, hau_qua_keywords: list[str]) -> list[dict]:
        """
        Tìm tội hình sự dựa trên hậu quả.
        Ví dụ: hau_qua_keywords = ["chết người", "thương tích nặng"]
        """
        keyword_str = " OR ".join(hau_qua_keywords)
        cypher = """
        CALL db.index.fulltext.queryNodes('khoanFullText', $keyword) 
        YIELD node AS k, score
        MATCH (d:DieuHinhSu)-[:CO_KHOAN]->(k)
        MATCH (ch:Chuong)-[:CO_DIEU]->(d)
        RETURN
            d.so       AS so_dieu,
            d.ten      AS ten_dieu,
            k.so       AS khoan,
            k.noi_dung AS noi_dung_khoan,
            ch.ten     AS chuong,
            score
        ORDER BY score DESC
        LIMIT 8
        """
        with self.driver.session(database=NEO4J.database) as s:
            return [dict(r) for r in s.run(cypher, keyword=keyword_str)]

    # ---------------------------------------------------------------
    # QUERY 4: Tìm mức phạt hành chính theo hành vi cụ thể
    # ---------------------------------------------------------------
    def search_hanh_chinh_by_hanh_vi(self, hanh_vi_keyword: str) -> list[dict]:
        """
        Tìm mức phạt hành chính liên quan đến hành vi.
        Ví dụ: hanh_vi_keyword = "vượt đèn đỏ"
        """
        cypher = """
        CALL db.index.fulltext.queryNodes('diemFullText', $keyword) 
        YIELD node AS p, score
        MATCH (d:DieuHanhChinh)-[:CO_DIEM]->(p)
        MATCH (d)-[:CO_KHOAN]->(k:Khoan)
        MATCH (ch:Chuong)-[:CO_DIEU]->(d)
        RETURN
            d.so       AS so_dieu,
            d.ten      AS ten_dieu,
            k.so       AS khoan,
            k.noi_dung AS noi_dung_khoan,
            p.ky_hieu  AS diem,
            p.noi_dung AS noi_dung_diem,
            ch.ten     AS chuong,
            score
        ORDER BY score DESC
        LIMIT 8
        """
        with self.driver.session(database=NEO4J.database) as s:
            return [dict(r) for r in s.run(cypher, keyword=hanh_vi_keyword)]

    # ---------------------------------------------------------------
    # QUERY 5: Graph traversal - tìm điều luật liên quan nhau
    # ---------------------------------------------------------------
    def find_related_laws(self, so_dieu: str, van_ban: str, depth: int = 2) -> list[dict]:
        """
        Tìm các điều luật liên quan (cùng chương, cùng phần).
        Dùng cho context mở rộng khi trả lời.
        """
        cypher = """
        MATCH (d:Dieu {so: $so_dieu, van_ban: $van_ban})
        MATCH (ch:Chuong)-[:CO_DIEU]->(d)
        MATCH (ch)-[:CO_DIEU]->(d_related:Dieu)
        WHERE d_related.so <> $so_dieu
        RETURN
            d_related.so   AS so_dieu,
            d_related.ten  AS ten_dieu,
            d_related.loai AS loai
        ORDER BY d_related.so
        LIMIT 10
        """
        with self.driver.session(database=NEO4J.database) as s:
            return [dict(r) for r in s.run(cypher, so_dieu=so_dieu, van_ban=van_ban)]

    # ---------------------------------------------------------------
    # QUERY 6: Tổng hợp tình huống - search CẢ 2 nguồn luật
    # ---------------------------------------------------------------
    def analyze_situation(self, keywords: list[str]) -> dict:
        """
        Query tổng hợp: tìm cả điều luật hình sự VÀ hành chính
        liên quan đến tình huống. Đây là query chính cho chatbot.
        """
        keyword_str = " ".join(keywords)

        hinh_su = self.search_by_keyword(keyword_str + " tội phạm hình sự")
        hanh_chinh = self.search_hanh_chinh_by_hanh_vi(keyword_str)

        # Lọc theo loại
        hinh_su_results = [r for r in hinh_su if r.get("loai_van_ban") == "Hình sự"]
        hc_results = [r for r in hanh_chinh] + [
            r for r in hinh_su if r.get("loai_van_ban") == "Hành chính"
        ]

        return {
            "hinh_su":    hinh_su_results[:4],
            "hanh_chinh": hc_results[:4],
            "keywords":   keywords,
        }

    # ---------------------------------------------------------------
    # QUERY 7: Xem toàn bộ graph stats (debug)
    # ---------------------------------------------------------------
    def get_stats(self) -> dict:
        cypher = """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(n) AS total
        ORDER BY total DESC
        """
        with self.driver.session(database=NEO4J.database) as s:
            rows = [dict(r) for r in s.run(cypher)]
            rel = s.run("MATCH ()-[r]->() RETURN count(r) AS total").single()
            return {"nodes": rows, "relationships": rel["total"]}


# ==============================================================================
# Quick test
# ==============================================================================
if __name__ == "__main__":
    svc = Neo4jService()
    try:
        print("📊 Stats:")
        stats = svc.get_stats()
        for row in stats["nodes"]:
            print(f"  {row['label']}: {row['total']}")
        print(f"  Relationships: {stats['relationships']}")

        print("\n🔍 Test search 'say rượu':")
        results = svc.search_by_keyword("say rượu gây tai nạn")
        for r in results:
            print(f"  [{r['van_ban']}] Điều {r['so_dieu']}: {r['ten_dieu']} (score={r['score']:.2f})")
    finally:
        svc.close()
