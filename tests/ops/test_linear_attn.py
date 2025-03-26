# -*- coding: utf-8 -*-

import os

import pytest
import torch

from fla.ops.linear_attn import chunk_linear_attn, fused_chunk_linear_attn, fused_recurrent_linear_attn
from fla.ops.linear_attn.naive import naive_chunk_linear_attn
from fla.utils import device
from utils import assert_close

compiled_mode = os.getenv("COMPILER_MODE") == "1"
if compiled_mode:
    test_b_list = [1]
    test_t_list = [64]
    test_t_varlen_list = test_t_list
    test_d_list = [32, 64, 128]
    test_gate_list = [1.0]
else:
    test_b_list = [2]
    test_t_list = [64, 128]
    test_t_varlen_list = [1, 7, 15, 63, 286, 300, 1024]
    test_d_list = [32, 64, 128]
    test_gate_list = [1, 0.1, 10]
test_h_list = [2]


@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("dtype", [torch.float])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
def test_fused_recurrent(
    B: int,
    H: int,
    T: int,
    D: int,
    dtype: torch.dtype
):
    torch.manual_seed(42)
    atol = 1e-3
    q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()

    do = torch.randn_like(v)
    ref = naive_chunk_linear_attn(q, k, v, normalize=False)
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None

    tri, _ = fused_recurrent_linear_attn(q, k, v, normalize=False)
    tri.backward(do)
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None

    assert ref.allclose(tri, 0, atol), f" o diff: {torch.abs(ref - tri).max()}"
    assert ref_dq.allclose(tri_dq, 0, atol), f"dq diff: {torch.abs(ref_dq - tri_dq).max()}"
    assert ref_dk.allclose(tri_dk, 0, atol), f"dk diff: {torch.abs(ref_dk - tri_dk).max()}"
    assert ref_dv.allclose(tri_dv, 0, atol), f"dv diff: {torch.abs(ref_dv - tri_dv).max()}"


@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("dtype", [torch.bfloat16])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
def test_chunk(
    B: int,
    H: int,
    T: int,
    D: int,
    dtype: torch.dtype
):
    torch.manual_seed(42)
    q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    h0 = torch.randn((B, H, D, D), dtype=dtype, device=device).requires_grad_()
    do = torch.randn_like(v)
    ref, ref_ht = fused_recurrent_linear_attn(q.to(torch.float32), k.to(torch.float32), v.to(
        torch.float32), initial_state=h0.to(torch.float32), output_final_state=True, normalize=False)
    ref = ref.to(dtype)
    ref_ht = ref_ht.to(dtype)
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None

    tri, tri_ht = chunk_linear_attn(q, k, v, initial_state=h0, output_final_state=True, normalize=False)
    tri.backward(do)
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None

    assert_close("  o", ref, tri, 0.007)
    assert_close(" ht", ref_ht, tri_ht, 0.008)
    assert_close(" dq", ref_dq, tri_dq, 0.008)
    assert_close(" dk", ref_dk, tri_dk, 0.008)
    assert_close(" dv", ref_dv, tri_dv, 0.008)


@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("dtype", [torch.bfloat16])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
def test_fused_chunk(
    B: int,
    H: int,
    T: int,
    D: int,
    dtype: torch.dtype
):
    torch.manual_seed(42)
    q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    h0 = torch.zeros((B, H, D, D), dtype=dtype, device=device).requires_grad_()
    do = torch.randn_like(v)
    ref, ref_ht = fused_recurrent_linear_attn(q.to(torch.float32), k.to(torch.float32), v.to(
        torch.float32), initial_state=h0.to(torch.float32), output_final_state=True, normalize=False)
    ref = ref.to(dtype)
    ref_ht = ref_ht.to(dtype)
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None

    tri, tri_ht = fused_chunk_linear_attn(q, k, v, initial_state=h0, output_final_state=True, normalize=False)
    tri.backward(do)
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None

    assert_close("  o", ref, tri, 0.007)
    assert_close(" ht", ref_ht, tri_ht, 0.008)
    assert_close(" dq", ref_dq, tri_dq, 0.008)
    assert_close(" dk", ref_dk, tri_dk, 0.008)
    assert_close(" dv", ref_dv, tri_dv, 0.008)
