"""分析脚本 — 依赖 pandas（故意的）"""
import pandas as pd
import json

df = pd.read_csv("data.csv")
result = df.groupby("category")["amount"].sum().to_dict()

with open("result.json", "w") as f:
    json.dump(result, f, indent=2)

print("Done:", result)
