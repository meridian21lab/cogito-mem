#!/usr/bin/env python3
"""Write a tiny, random-weight GGUF of llama.cpp's ``gemma-embedding2`` architecture (EmbeddingGemma 2).

It lets the llama.cpp tests run without downloading the real model: the tokenizer is
copied verbatim from llama.cpp's ``models/ggml-vocab-gemma-4.gguf``, so token counts are
real, while the weights are seeded random values, so the vectors carry no meaning.

    python scripts/make_tiny_embeddinggemma2.py --llama-cpp ~/src/llama.cpp --out tiny.gguf
    COGITO_MEM_TEST_LLAMA_SERVER=~/src/llama.cpp/build/bin/llama-server \
    COGITO_MEM_TEST_MODEL=tiny.gguf pytest -m llama

The architecture keys mirror what llama.cpp's ``conversion/gemma.py`` writes for
EmbeddingGemma2Model; the tensors mirror ``src/models/gemma-embedding2.cpp``.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np


def _llama_cpp_dir() -> Path:
    for i, arg in enumerate(sys.argv):
        if arg == "--llama-cpp" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).expanduser()
        if arg.startswith("--llama-cpp="):
            return Path(arg.split("=", 1)[1]).expanduser()
    sys.exit("usage: make_tiny_embeddinggemma2.py --llama-cpp <llama.cpp checkout> --out <file.gguf>")


LLAMA_CPP = _llama_cpp_dir()
# The checkout's gguf-py matches its architecture constants; prefer it to a pip-installed gguf.
sys.path.insert(0, str(LLAMA_CPP / "gguf-py"))

import gguf  # noqa: E402
from gguf import GGUFValueType as VT  # noqa: E402

ARCH = gguf.MODEL_ARCH.GEMMA_EMBEDDING2
ARCH_NAME = gguf.MODEL_ARCH_NAMES[ARCH]  # "gemma-embedding2"

# ---- tiny config (HF-style names in comments) -------------------------------------------
SEED = 1234
N_LAYER = 4                       # num_hidden_layers
LAYER_TYPES = ["sliding_attention", "sliding_attention", "sliding_attention", "full_attention"]
N_CTX = 2048                      # max_position_embeddings
N_EMBD = 64                       # hidden_size
N_FF = 128                        # intermediate_size
N_HEAD = 2                        # num_attention_heads
N_HEAD_KV = 1                     # num_key_value_heads
HEAD_DIM_SWA = 32                 # head_dim
HEAD_DIM_FULL = 32                # global_head_dim (must equal for K and V; arch requires k==v)
N_EMBD_PER_LAYER = 16             # hidden_size_per_layer_input
N_EMBD_OUT = 768                  # embedding_dim (output projection, like the real model)
HF_SLIDING_WINDOW = 256           # HF value is bidirectional half-width; GGUF stores 2x
ROPE_THETA_FULL = 1_000_000.0     # rope_parameters.full_attention.rope_theta
ROPE_THETA_SWA = 10_000.0         # rope_parameters.sliding_attention.rope_theta
PARTIAL_ROTARY_SWA = 1.0
RMS_EPS = 1e-6


def copy_tokenizer_kvs(reader: gguf.GGUFReader, writer: gguf.GGUFWriter) -> list[str]:
    copied = []
    for key, field in reader.fields.items():
        if not key.startswith("tokenizer."):
            continue
        main_type = field.types[0]
        if main_type == VT.ARRAY:
            sub_type = field.types[-1]
            if sub_type == VT.STRING:
                # keep raw bytes (do not round-trip through str) so nothing is altered
                val = [bytes(field.parts[i]) for i in field.data]
            else:
                val = field.contents()
            writer.add_key_value(key, val, VT.ARRAY, sub_type=sub_type)
        elif main_type == VT.STRING:
            writer.add_key_value(key, bytes(field.parts[field.data[0]]), VT.STRING)
        else:
            writer.add_key_value(key, field.contents(), main_type)
        copied.append(key)
    return copied


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llama-cpp", type=Path, required=True, help="a llama.cpp checkout")
    ap.add_argument("--vocab", type=Path, default=LLAMA_CPP / "models" / "ggml-vocab-gemma-4.gguf")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    reader = gguf.GGUFReader(args.vocab)
    n_vocab = len(reader.fields["tokenizer.ggml.tokens"].data)

    w = gguf.GGUFWriter(args.out, ARCH_NAME)

    # ---- general ----
    w.add_type(gguf.GGUFType.MODEL)
    w.add_name("tiny-embeddinggemma2-random")
    w.add_description("Tiny random-weight EmbeddingGemma2 for integration tests (outputs are meaningless)")
    w.add_file_type(gguf.LlamaFileType.MOSTLY_F16)
    w.add_quantization_version(gguf.GGML_QUANT_VERSION)

    # ---- TextModel.set_gguf_parameters ----
    w.add_block_count(N_LAYER)
    w.add_context_length(N_CTX)
    w.add_embedding_length(N_EMBD)
    w.add_feed_forward_length(N_FF)
    w.add_head_count(N_HEAD)
    w.add_head_count_kv(N_HEAD_KV)
    w.add_rope_freq_base(ROPE_THETA_FULL)
    w.add_rope_freq_base_swa(ROPE_THETA_SWA)
    w.add_layer_norm_rms_eps(RMS_EPS)
    # ---- Gemma3Model.set_gguf_parameters ----
    w.add_sliding_window(2 * HF_SLIDING_WINDOW)  # EmbeddingGemma2 overrides with 2x HF window
    # ---- Gemma4Model.set_gguf_parameters ----
    w.add_shared_kv_layers(0)
    w.add_embedding_length_per_layer_input(N_EMBD_PER_LAYER)
    swa_layers = [t == "sliding_attention" for t in LAYER_TYPES]
    w.add_sliding_window_pattern(swa_layers)
    w.add_key_length(HEAD_DIM_FULL)
    w.add_value_length(HEAD_DIM_FULL)
    w.add_key_length_swa(HEAD_DIM_SWA)
    w.add_value_length_swa(HEAD_DIM_SWA)
    w.add_rope_dimension_count(HEAD_DIM_FULL)
    w.add_rope_dimension_count_swa(int(HEAD_DIM_SWA * PARTIAL_ROTARY_SWA))
    # ---- EmbeddingGemma2Model.set_gguf_parameters ----
    w.add_embedding_length_out(N_EMBD_OUT)
    w.add_causal_attention(False)
    w.add_pooling_type(gguf.PoolingType.MEAN)

    # ---- tokenizer (verbatim from the Gemma 4 vocab GGUF) ----
    copied = copy_tokenizer_kvs(reader, w)

    # ---- tensors ----
    # numpy shape is the reverse of ggml ne: ggml {ne0, ne1} == numpy (ne1, ne0)
    rng = np.random.default_rng(SEED)

    def mat(ne0: int, ne1: int, dtype=np.float16) -> np.ndarray:
        # ggml {ne0 (in), ne1 (out)}; scale ~ 1/sqrt(fan_in)
        return (rng.standard_normal((ne1, ne0), dtype=np.float32) / np.sqrt(ne0)).astype(dtype)

    def norm(n: int) -> np.ndarray:
        return (1.0 + 0.05 * rng.standard_normal(n, dtype=np.float32)).astype(np.float32)

    def name(t: gguf.MODEL_TENSOR, bid: int | None = None) -> str:
        base = gguf.TENSOR_NAMES[t]
        return (base.format(bid=bid) if bid is not None else base) + ".weight"

    T = gguf.MODEL_TENSOR
    w.add_tensor(name(T.TOKEN_EMBD), (rng.standard_normal((n_vocab, N_EMBD), dtype=np.float32) * 0.05).astype(np.float16))
    w.add_tensor(name(T.PER_LAYER_MODEL_PROJ), mat(N_EMBD, N_EMBD_PER_LAYER * N_LAYER))
    w.add_tensor(name(T.PER_LAYER_PROJ_NORM), norm(N_EMBD_PER_LAYER))
    w.add_tensor(name(T.OUTPUT_NORM), norm(N_EMBD))
    w.add_tensor(name(T.OUTPUT), mat(N_EMBD, N_EMBD_OUT))

    for i, lt in enumerate(LAYER_TYPES):
        hd = HEAD_DIM_SWA if lt == "sliding_attention" else HEAD_DIM_FULL
        w.add_tensor(name(T.ATTN_NORM, i), norm(N_EMBD))
        w.add_tensor(name(T.ATTN_Q, i), mat(N_EMBD, hd * N_HEAD))
        w.add_tensor(name(T.ATTN_K, i), mat(N_EMBD, hd * N_HEAD_KV))
        w.add_tensor(name(T.ATTN_V, i), mat(N_EMBD, hd * N_HEAD_KV))
        w.add_tensor(name(T.ATTN_OUT, i), mat(hd * N_HEAD, N_EMBD))
        w.add_tensor(name(T.ATTN_Q_NORM, i), norm(hd))
        w.add_tensor(name(T.ATTN_K_NORM, i), norm(hd))
        w.add_tensor(name(T.ATTN_POST_NORM, i), norm(N_EMBD))
        w.add_tensor(name(T.FFN_PRE_NORM, i), norm(N_EMBD))   # "blk.N.ffn_norm"
        w.add_tensor(name(T.FFN_GATE, i), mat(N_EMBD, N_FF))
        w.add_tensor(name(T.FFN_UP, i), mat(N_EMBD, N_FF))
        w.add_tensor(name(T.FFN_DOWN, i), mat(N_FF, N_EMBD))
        w.add_tensor(name(T.FFN_POST_NORM, i), norm(N_EMBD))
        w.add_tensor(name(T.PER_LAYER_INP_GATE, i), mat(N_EMBD, N_EMBD_PER_LAYER))
        w.add_tensor(name(T.PER_LAYER_PROJ, i), mat(N_EMBD_PER_LAYER, N_EMBD))
        w.add_tensor(name(T.PER_LAYER_POST_NORM, i), norm(N_EMBD))
        w.add_tensor(name(T.LAYER_OUT_SCALE, i), np.array([1.0 + 0.01 * i], dtype=np.float32))

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()

    size = os.path.getsize(args.out)
    print(f"wrote {args.out} ({size / 1e6:.1f} MB), n_vocab={n_vocab}, tokenizer KVs copied: {len(copied)}")
    for k in copied:
        print("  ", k)


if __name__ == "__main__":
    main()
