# Development

```sh
pip install -e '.[test]'
pytest                                   # the llama.cpp tests are skipped without a model
COGITO_MEM_TEST_LLAMA_SERVER=$(which llama-server) \
COGITO_MEM_TEST_MODEL=~/.cogito-mem/models/embeddinggemma-2-Q8_0.gguf pytest
```

`scripts/make_tiny_embeddinggemma2.py` writes a 50 MB random-weight model of the same architecture with the real
tokenizer, enough to test the llama.cpp path without downloading the model; CI builds llama.cpp and does that.
The stage-0 measurements:

```sh
cogito-mem eval locomo --data locomo10.json --search hybrid --out results/locomo.json
cogito-mem eval longmemeval-recall --data longmemeval_s_cleaned.json --out results/lme-recall.json   # session R@k, no LLM
cogito-mem eval run --data longmemeval_m.json --arm U2 --out results/u2.json      # LongMemEval, arms U1-U3, R
cogito-mem eval compare results/u1.json results/u2.json --budget 300
COGITO_MEM_GPU_LAYERS=0 cogito-mem bench speed --data longmemeval_m.json --tokens 10M --out results/speed.json
```

## Releasing

1. Raise the version in `pyproject.toml`, `src/cogito_mem/__init__.py` and `server.json` (twice), run `uv lock`, add
   the version's section to `CHANGELOG.md` (what changes for people who use Cogi, and what to do when updating), and
   merge to `main`.
2. Create the GitHub release `v<version>` on `main`, with that `CHANGELOG.md` section as its notes (not generated
   notes). The release workflow checks the versions, publishes to PyPI and the MCP Registry, and attaches the files.
3. Point the plugin at the new release: `python scripts/pin_plugin.py <version>`, then merge `plugin/` to `main`.
   The plugin runs the released package (`uvx cogito-mem==<version>`), so this step needs the release on PyPI; the
   plugin directory picks up the commit by itself.

The plugin in `plugin/` always runs a release. To try unreleased code in Claude Code, install it from the checkout
instead (`uv tool install -e .`, then `cogito-mem install claude-code`), and uninstall the plugin while you do.

| Document | What is in it |
|---|---|
| [`docs/install.md`](install.md) | Every way to install, upgrade, remove and troubleshoot. |
| [`docs/requirements.md`](requirements.md) | The API, the tests, the gates, the stages and the decision log. |
| [`docs/literature/`](literature/) | How other memory systems work and name things; benchmarks. |
