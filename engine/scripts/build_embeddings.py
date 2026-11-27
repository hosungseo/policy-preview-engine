"""Convert tantara embedding shards into one row-normalized float16 matrix on the SSD.

Run: ../.venv/bin/python scripts/build_embeddings.py
"""
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pp import config  # noqa: E402


def main(src: Path | None = None, dim: int = 1024) -> None:
    src = src or (config.data_dir() / "emb" / "parquet" / "data")
    shards = sorted(Path(src).glob("train-*.parquet"))
    if not shards:
        raise SystemExit(f"no shards in {src}")
    total = sum(pq.ParquetFile(s).metadata.num_rows for s in shards)
    config.emb_matrix().parent.mkdir(parents=True, exist_ok=True)
    out = np.lib.format.open_memmap(config.emb_matrix(), mode="w+", dtype=np.float16, shape=(total, dim))
    row = 0
    with open(config.emb_uuids(), "w", encoding="utf-8") as uuid_file:
        for shard in shards:
            for batch in pq.ParquetFile(shard).iter_batches(batch_size=20000, columns=["uuid", "embedding"]):
                uuids = batch.column(0).to_pylist()
                flat = batch.column(1).flatten().to_numpy(zero_copy_only=False).astype(np.float32)
                if flat.shape[0] != len(uuids) * dim:
                    raise SystemExit(f"{shard.name}: expected dim {dim}, got {flat.shape[0] / len(uuids)}")
                mat = flat.reshape(len(uuids), dim)
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                out[row:row + len(uuids)] = (mat / norms).astype(np.float16)
                uuid_file.write("\n".join(uuids) + "\n")
                row += len(uuids)
            print(f"{shard.name}: {row}/{total}", flush=True)
    out.flush()
    if row != total:
        raise SystemExit(f"row mismatch {row} != {total}")
    print(f"done {config.emb_matrix()} rows={total}")


if __name__ == "__main__":
    main()
