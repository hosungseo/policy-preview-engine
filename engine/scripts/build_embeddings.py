"""Compute local persona embeddings from original SQLite text (never from embedding shards).

Run from the repository root: .venv/bin/python engine/scripts/build_embeddings.py --help
The complete index becomes available only after its directory is atomically published.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pp import config, personas, semantic  # noqa: E402


def main(*, db_path: Path | None = None, batch_size: int = 16, limit: int | None = None,
         encode=None) -> dict:
    """A --limit pilot records throughput but cannot activate a partial persona index."""
    if batch_size < 1 or (limit is not None and limit < 1):
        raise ValueError("batch_size and limit must be positive")
    encode = encode or semantic.embed_documents
    db_path = Path(db_path or config.persona_db())
    conn = personas.connect(db_path)
    target = config.emb_dir() if limit is None else config.emb_dir().with_name(config.emb_dir().name + f"-pilot-{limit}")
    if target.exists():
        conn.close()
        raise FileExistsError(f"{target} already exists; use a separate PP_DATA_DIR to rebuild")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    started = time.perf_counter()
    try:
        conn.execute("BEGIN")  # COUNT and streamed text share one read-only snapshot.
        total = conn.execute("SELECT COUNT(*) FROM persona").fetchone()[0]
        count = min(total, limit) if limit is not None else total
        if not count:
            raise ValueError("persona DB is empty")
        cursor = conn.execute("SELECT uuid, persona, professional_persona, family_persona, cultural_background, "
                              "sex, age, district, occupation, family_type FROM persona ORDER BY id LIMIT ?", (count,))
        matrix = np.lib.format.open_memmap(staging / "emb.f16.npy", mode="w+", dtype=np.float16,
                                          shape=(count, config.EMBEDDING_DIM))
        done = 0
        seen = set()
        with (staging / "emb_uuids.txt").open("w", encoding="utf-8") as uuid_file:
            while rows := cursor.fetchmany(batch_size):
                docs, uuids = [], []
                for row in rows:
                    item = dict(row)
                    uuid = item["uuid"]
                    if not isinstance(uuid, str) or not uuid or "\n" in uuid or "\r" in uuid or uuid in seen:
                        raise ValueError("missing/duplicate/invalid persona UUID")
                    seen.add(uuid)
                    uuids.append(uuid)
                    item["name"] = personas.extract_name(item.get("persona"))
                    docs.append(semantic.persona_text_without_name(item))
                vectors = np.asarray(encode(docs, batch_size=batch_size), dtype=np.float32)
                if vectors.shape != (len(rows), config.EMBEDDING_DIM) or not np.isfinite(vectors).all():
                    raise ValueError("encoder returned invalid shape or non-finite vectors")
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                if np.any(norms == 0):
                    raise ValueError("encoder returned a zero vector")
                matrix[done:done + len(rows)] = (vectors / norms).astype(np.float16)
                uuid_file.write("\n".join(uuids) + "\n")
                done += len(rows)
                if done == count or done % (batch_size * 100) == 0:
                    print(f"{done}/{count} personas; {time.perf_counter()-started:.1f}s", flush=True)
        if done != count:
            raise ValueError(f"persona row count changed: {done} != {count}")
        matrix.flush()
        del matrix
        elapsed = time.perf_counter() - started
        manifest = {**semantic.embedding_identity(), "rows": done, "source_rows": total,
                    "complete": limit is None, "source": "persona_sqlite_original_text",
                    "source_db": str(db_path.resolve()), "name_removed": True,
                    "seconds": round(elapsed, 3), "personas_per_second": round(done / elapsed, 3)}
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.rename(staging, target)
        print(f"{'pilot only' if limit is not None else 'ready'}: {target}", flush=True)
        return manifest
    finally:
        conn.close()
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="read-only source persona SQLite DB (default: PP_PERSONA_DB)")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, help="timing pilot only; never activates a partial index")
    args = parser.parse_args()
    main(db_path=args.db, batch_size=args.batch_size, limit=args.limit)
