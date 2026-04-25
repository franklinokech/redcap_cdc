import csv

with open("data_dictionary.csv", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

from data_quality.schema.dictionary_loader import REDCapDictionaryLoader

loader = REDCapDictionaryLoader(rows)
schema = loader.load()

# Print each key and value on separate lines
for key, value in schema.items():
    print(f"{key}: {value}")
