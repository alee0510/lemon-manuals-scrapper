from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.configs.settings import settings
from src.utils.discover import discover, DiscoveredDataset
from src.utils.writer import write_dataset, is_dataset_already_written, _crawl_and_extract

def _process_one_dataset(dataset: DiscoveredDataset, output_dir: Path, skip_existing: bool) -> tuple[str, str]:
    """
    Runs in a worker process — must be a top-level function (not a
    closure/lambda) so it's picklable by ProcessPoolExecutor.
    Returns (dataset_name, status) so the main process can report
    progress without workers needing to share state.
    """
    if skip_existing and is_dataset_already_written(output_dir, dataset):
        return dataset.name, "skipped (already exists)"

    graph, content_map = _crawl_and_extract(dataset)
    write_dataset(output_dir, dataset, graph, content_map)
    return dataset.name, f"done ({len(content_map)} pages)"

def main():
    result = discover(settings.data_dir)
    print(f"Found {len(result.datasets)} dataset(s) in {settings.data_dir}")

    for skipped in result.skipped:
        print(f"Skipped - {skipped.name}: {skipped.reason.value}")

    settings.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nProcessing {len(result.datasets)} dataset(s) with {settings.max_workers} worker(s)...")

    with ProcessPoolExecutor(max_workers=settings.max_workers) as pool:
        futures = {
            pool.submit(_process_one_dataset, ds, settings.output_dir, settings.skip_existing): ds
            for ds in result.datasets
        }
        for future in as_completed(futures):
            ds = futures[future]
            try:
                name, status = future.result()
                print(f"[{name}] {status}")
            except Exception as exc:
                print(f"[{ds.name}] FAILED: {exc!r}")

if __name__ == "__main__":
    main()