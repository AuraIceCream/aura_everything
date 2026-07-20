# Corpus verification gate

Date: 2026-07-18 (Asia/Calcutta)

The acquisition pipeline's full verifier was run against every manifest entry
whose status was `complete` before this processing project was built.

- Checked entries: **3,659**
- Successful (`ok`) entries: **3,659**
- Non-`ok` entries: **0**
- Verifier stderr bytes: **0**
- Wikipedia JSON batches separately parsed: **1,693 / 1,693**

The full pass validated compressed-stream integrity, archive safety, XML/JSON
openability, PDF signatures, and provider checksums where available. Historical
`.part`, `planned`, and interrupted manifest rows were not treated as completed
source files and are excluded by the processing inventory.

The processing pipeline therefore treats `D:\aura_data\AURA-Bio-Corpus` as a
frozen, read-only acquisition input.

