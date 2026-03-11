import json
import csv
from typing import Dict, List, Any

def json_to_csv(json_file: str, csv_file: str):
    """
    Chuyển đổi file JSON sang CSV.
    
    Cấu trúc CSV:
    - Mỗi dòng đại diện cho một điểm (point) hoặc khoản (clause) hoặc điều (article)
    - Các cột: Phần, Chương, Số điều, Tiêu đề điều, Nội dung điều, Số khoản, Nội dung khoản, Điểm, Nội dung điểm
    """
    
    # Đọc file JSON
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Tạo danh sách các dòng CSV
    rows = []
    
    # Duyệt qua các phần
    for part in data.get("parts", []):
        part_name = part.get("name", "")
        
        # Duyệt qua các chương
        for chapter in part.get("chapters", []):
            chapter_name = chapter.get("name", "")
            
            # Duyệt qua các điều
            for article in chapter.get("articles", []):
                article_num = article.get("number", "")
                article_title = article.get("title", "")
                article_content = article.get("content", "")
                
                clauses = article.get("clauses", [])
                
                # Nếu điều không có khoản, tạo một dòng cho điều
                if not clauses:
                    rows.append({
                        "Phần": part_name,
                        "Chương": chapter_name,
                        "Số điều": article_num,
                        "Tiêu đề điều": article_title,
                        "Nội dung điều": article_content,
                        "Số khoản": "",
                        "Nội dung khoản": "",
                        "Điểm": "",
                        "Nội dung điểm": ""
                    })
                else:
                    # Duyệt qua các khoản
                    for clause in clauses:
                        clause_num = clause.get("number", "")
                        clause_content = clause.get("content", "")
                        points = clause.get("points", [])
                        
                        # Nếu khoản không có điểm, tạo một dòng cho khoản
                        if not points:
                            rows.append({
                                "Phần": part_name,
                                "Chương": chapter_name,
                                "Số điều": article_num,
                                "Tiêu đề điều": article_title,
                                "Nội dung điều": article_content,
                                "Số khoản": clause_num,
                                "Nội dung khoản": clause_content,
                                "Điểm": "",
                                "Nội dung điểm": ""
                            })
                        else:
                            # Duyệt qua các điểm
                            for point in points:
                                point_letter = point.get("letter", "")
                                point_content = point.get("content", "")
                                
                                rows.append({
                                    "Phần": part_name,
                                    "Chương": chapter_name,
                                    "Số điều": article_num,
                                    "Tiêu đề điều": article_title,
                                    "Nội dung điều": article_content,
                                    "Số khoản": clause_num,
                                    "Nội dung khoản": clause_content,
                                    "Điểm": point_letter,
                                    "Nội dung điểm": point_content
                                })
                
                # Xử lý direct_points nếu có (điểm trực tiếp trong điều, không có khoản)
                if article.get("direct_points"):
                    for point in article.get("direct_points", []):
                        point_letter = point.get("letter", "")
                        point_content = point.get("content", "")
                        
                        rows.append({
                            "Phần": part_name,
                            "Chương": chapter_name,
                            "Số điều": article_num,
                            "Tiêu đề điều": article_title,
                            "Nội dung điều": article_content,
                            "Số khoản": "",
                            "Nội dung khoản": "",
                            "Điểm": point_letter,
                            "Nội dung điểm": point_content
                        })
    
    # Ghi ra file CSV
    if rows:
        fieldnames = ["Phần", "Chương", "Số điều", "Tiêu đề điều", "Nội dung điều", 
                     "Số khoản", "Nội dung khoản", "Điểm", "Nội dung điểm"]
        
        with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        return len(rows)
    else:
        return 0

if __name__ == "__main__":
    import sys
    import io
    
    # Fix encoding cho Windows console
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    json_file = "giaothong.json"
    csv_file = "giaothong.csv"
    
    print(f"[*] Dang doc file JSON: {json_file}...")
    
    try:
        total_rows = json_to_csv(json_file, csv_file)
        
        print(f"[+] Thanh cong!")
        print(f"[*] Da chuyen doi {total_rows} dong sang CSV")
        print(f"[*] Ket qua luu tai: {csv_file}")
        
    except Exception as e:
        print(f"[-] Loi: {e}")
        import traceback
        traceback.print_exc()
