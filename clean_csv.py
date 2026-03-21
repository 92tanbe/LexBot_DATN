import pandas as pd

df = pd.read_csv("blhs_2025.csv")

df["article_id"] = df["Số điều"]

df["clause_id"] = df.apply(
    lambda x: f"{x['Số điều']}_{x['Số khoản']}" 
    if pd.notna(x["Số khoản"]) else None,
    axis=1
)

df["point_id"] = df.apply(
    lambda x: f"{x['Số điều']}_{x['Số khoản']}_{x['Điểm']}"
    if pd.notna(x["Điểm"]) else None,
    axis=1
)

df.to_csv("law_clean.csv", index=False)