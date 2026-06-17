# Enrichment scripts

Bản v1 đã sinh sẵn CSV nâng cấp trong `neo4j_import/`.
Nguồn đầu vào là `data/blhs_from_pdf_normalized.base.json` - đây là dữ liệu đã parse từ PDF trong bộ RAR/starter kit, không phải `deepseek_merged.json` cũ.

Các node như `Requirement`, `QuantityThreshold`, `Exception` được sinh bằng rule-based extractor. Khi dùng cho nghiệp vụ pháp lý thật, nên review thủ công các điều có ngưỡng định lượng phức tạp như ma túy, môi trường, lâm sản, tham nhũng.
