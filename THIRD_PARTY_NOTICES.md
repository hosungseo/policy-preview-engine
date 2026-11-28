# Third-party software terms

The engine's source code is Apache-2.0 (see [LICENSE](LICENSE)). That license
does not replace the licenses of separately installed packages, native libraries,
model weights, or data. See [data/SOURCES.md](data/SOURCES.md) for data terms.

The optional GPU and semantic environment in
[`engine/requirements-semantic.txt`](engine/requirements-semantic.txt) installs
NVIDIA and other native packages with their own terms. These extras are not
required for the key-less archived MCP examples.

| Component family | Separate terms to review for the actual installed artifacts |
| --- | --- |
| NVIDIA CUDA/toolkit packages, including CUDA CCCL, nvJitLink and cuSPARSELt | NVIDIA proprietary licenses/EULAs apply to some packages; metadata for others does not fully state their terms. Inspect the exact package and bundled notices. |
| SciPy and bundled numerical runtimes | Project and bundled components have distinct terms, including BSD, LGPL-2.1-or-later (libquadmath), and GPL-3.0-or-later **with GCC Runtime Library Exception 3.1** (libgfortran/libgcc). Preserve the exception and review the wheel actually distributed. |
| Native web dependencies, including sharp/libvips platform packages | May include LGPL-3.0-or-later components as recorded in `web/package-lock.json`; inspect platform-specific binaries and accompanying notices. |

Using or distributing this repository's source alone under Apache-2.0 does not
redistribute these separately downloaded dependency binaries. Redistributing an
installed environment, wheel bundle, container image, or other artifact that
contains them requires compliance with their own terms, including applicable
license/notice, source availability, and relinking requirements. A source-only
release is not clearance for every possible binary or image distribution.

Before redistributing such an artifact, inventory its exact versions and bundled
libraries, retain their license texts and notices, and satisfy the obligations
that apply to that artifact. This summary does not relicense third-party software
under Apache-2.0 or assert that unknown/proprietary terms have been cleared.
