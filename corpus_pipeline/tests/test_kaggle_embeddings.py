import argparse
import gzip
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "kaggle" / "aura_kaggle_embeddings.py"
SPEC = importlib.util.spec_from_file_location("aura_kaggle_embeddings", SCRIPT)
assert SPEC and SPEC.loader
KAGGLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KAGGLE)


class KaggleEmbeddingRoundTripTests(unittest.TestCase):
    def test_prepare_and_import_preserve_source_row_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root = root / "chunks"
            source_dir = chunk_root / "wikipedia_biology"
            source_dir.mkdir(parents=True)
            chunk_path = source_dir / "sample.jsonl.gz"
            with gzip.open(chunk_path, "wt", encoding="utf-8") as handle:
                for index in range(5):
                    handle.write(json.dumps({"chunk_id": f"c-{index}", "text": f"biology {index}"}) + "\n")

            state_db = root / "pipeline.sqlite3"
            connection = sqlite3.connect(state_db)
            connection.execute(
                "CREATE TABLE processed_inputs (output_path TEXT, records INTEGER, stage TEXT)"
            )
            connection.execute(
                "INSERT INTO processed_inputs VALUES (?, ?, ?)",
                (str(chunk_path), 5, "chunk"),
            )
            connection.commit()
            connection.close()

            dataset = root / "dataset"
            KAGGLE.prepare(
                argparse.Namespace(
                    chunk_root=chunk_root,
                    output=dataset,
                    state_db=state_db,
                    profile="open-core",
                    bundle_gib=0.001,
                    max_task_chunks=2,
                    job_chunks=3,
                    model=KAGGLE.MODEL,
                    kaggle_username=None,
                    dataset_slug="test",
                    force=False,
                )
            )
            manifest = json.loads((dataset / "embedding-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_chunks"], 5)
            self.assertEqual(len(manifest["jobs"]), 2)

            kaggle_output = root / "kaggle-output"
            profile_output = kaggle_output / "open-core"
            profile_output.mkdir(parents=True)
            for job in manifest["jobs"]:
                vectors = np.empty((job["chunks"], KAGGLE.DIMENSIONS), dtype=np.float16)
                segments = []
                offset = 0
                for task in job["tasks"]:
                    for row_offset in range(task["records"]):
                        vectors[offset + row_offset].fill(task["original_start"] + row_offset)
                    segments.append(
                        {
                            "source_id": task["source_id"],
                            "chunk_relpath": task["chunk_relpath"],
                            "original_start": task["original_start"],
                            "count": task["records"],
                            "output_offset": offset,
                            "input_signature": task["input_signature"],
                        }
                    )
                    offset += task["records"]
                vector_name = f"{job['job_id']}.vectors.npy"
                np.save(profile_output / vector_name, vectors, allow_pickle=False)
                (profile_output / f"{job['job_id']}.complete.json").write_text(
                    json.dumps(
                        {
                            "job_id": job["job_id"],
                            "model": KAGGLE.MODEL,
                            "dimensions": KAGGLE.DIMENSIONS,
                            "vector_file": vector_name,
                            "segments": segments,
                        }
                    ),
                    encoding="utf-8",
                )

            embedding_root = root / "embeddings"
            result = KAGGLE.import_outputs(
                argparse.Namespace(
                    kaggle_output=kaggle_output,
                    chunk_root=chunk_root,
                    embedding_root=embedding_root,
                )
            )
            self.assertEqual(result["vectors"], 5)
            imported = np.load(
                embedding_root / "wikipedia_biology" / "sample.vectors.npy",
                allow_pickle=False,
            )
            self.assertEqual(imported.shape, (5, KAGGLE.DIMENSIONS))
            np.testing.assert_array_equal(imported[:, 0], np.arange(5, dtype=np.float16))
            marker = json.loads(
                (embedding_root / "wikipedia_biology" / "sample.complete.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(marker["source_chunk_file"], str(chunk_path))

    def test_reads_kaggle_auto_expanded_tar_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expanded = root / "bundle-000" / "chunks" / "wikipedia_biology"
            expanded.mkdir(parents=True)
            member = expanded / "sample.jsonl.gz"
            with gzip.open(member, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"text": "cell biology"}) + "\n")

            task = {
                "bundle": "bundle-000.tar",
                "member": "chunks/wikipedia_biology/sample.jsonl.gz",
            }
            rows = list(KAGGLE._task_rows(root, task, {}))
            self.assertEqual(rows, [{"text": "cell biology"}])

    def test_reads_kaggle_expanded_and_part_member_names(self) -> None:
        for mounted_name in ("sample.jsonl", "sample.jsonl.part"):
            with self.subTest(mounted_name=mounted_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                expanded = root / "bundle-000" / "chunks" / "wikipedia_biology"
                expanded.mkdir(parents=True)
                (expanded / mounted_name).write_text(
                    json.dumps({"text": mounted_name}) + "\n", encoding="utf-8"
                )
                task = {
                    "bundle": "bundle-000.tar",
                    "member": "chunks/wikipedia_biology/sample.jsonl.gz",
                }
                rows = list(KAGGLE._task_rows(root, task, {}))
                self.assertEqual(rows, [{"text": mounted_name}])


if __name__ == "__main__":
    unittest.main()
