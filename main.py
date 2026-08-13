from src.configs.settings import settings
from src.utils.discover import discover
from src.utils.crawler import crawler

def main():
    result = discover(settings.data_dir)
    print(f"Found {len(result.datasets)} dataset(s) in {settings.data_dir}")

    for skipped in result.skipped:
        print(f"Skipped - {skipped.name}: {skipped.reason.value}")

    for dataset in result.datasets:
        print(f"\nProcessing dataset: {dataset.name}")
        print(f"Total .html file {dataset.html_file_count}")

        graph = crawler(dataset)
        print(f"\nBuilt site graph for dataset: {graph.dataset_name}")
        print(f"Nodes: {len(graph.nodes)}")
        print(f"Broken links: {len(graph.broken_links)}")

        # 2 sample pages
        for node in list(graph.nodes.values())[:2]:
            print(f"- Node: {node.page_path} \n ==>> Parent: {node.parents} \n ==> Children: {node.children} \n ==> Type: {node.page_type} \n ==> Breadcrumbs: {node.breadcrumbs} \n")

if __name__ == "__main__":
    main()
