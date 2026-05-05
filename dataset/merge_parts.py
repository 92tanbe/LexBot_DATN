# Chạy: python merge_parts.py (trong thư mục dataset hoặc truyền đủ đường dẫn)
"""Gộp deepseek_part1.json + deepseek_part2.json thành một file (mảng parts nối tuần tự)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
OUT_NAME = "deepseek_merged.json"


def main() -> None:
    d1 = json.loads((ROOT / "deepseek_part1.json").read_text(encoding="utf-8"))
    d2 = json.loads((ROOT / "deepseek_part2.json").read_text(encoding="utf-8"))
    merged = {"parts": d1["parts"] + d2["parts"]}
    path = ROOT / OUT_NAME
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path, "| parts:", len(merged["parts"]))


if __name__ == "__main__":
    main()
