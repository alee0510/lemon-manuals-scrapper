from src.configs.settings import settings
from src.utils.discover import discover
from src.utils.crawler import crawler
from src.utils.writer import write_dataset

def main():
    result = discover(settings.data_dir)
    print(f"Found {len(result.datasets)} dataset(s) in {settings.data_dir}")

    for skipped in result.skipped:
        print(f"Skipped - {skipped.name}: {skipped.reason.value}")

    settings.output_dir.mkdir(parents=True, exist_ok=True)

    for dataset in result.datasets:
        print(f"\nProcessing dataset: {dataset.name}")
        print(f"Total .html file {dataset.html_file_count}")

        graph = crawler(dataset)
        print(f"Built site graph for dataset: {graph.dataset_name}")
        print(f"Nodes: {len(graph.nodes)}")
        print(f"Broken links: {len(graph.broken_links)}")

        dataset_dir = write_dataset(settings.output_dir, dataset, graph)
        page_count = len(list((dataset_dir / "pages").glob("*.json")))
        print(f"Wrote {page_count} page JSON file(s) to {dataset_dir}")

if __name__ == "__main__":
    main()