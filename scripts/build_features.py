from src.crispdm.features import build_features, persist_features

df = build_features()
persist_features(df)
print("Feature rows:", len(df))
