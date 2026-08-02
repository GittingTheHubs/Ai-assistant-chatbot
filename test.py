import pandas as pd

df = pd.read_excel("products_cleaned.xlsx")

print(df.columns.tolist())
print(df.iloc[0]["Description"][:500])