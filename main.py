from src.configs.settings import settings
from src.extractor.discover import discover

def main():
    result = discover(settings.data_dir)
    print(f"Found {len(result.datasets)} dataset(s) in {settings.data_dir}")
    for skipped in result.skipped:
        print(f"skipped {skipped.name}: {skipped.reason.value}")
    for dataset in result.datasets:
        print(f"dataset: {dataset.name}({dataset.index_path})")


if __name__ == "__main__":
    main()
