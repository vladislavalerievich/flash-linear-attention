# -*- coding: utf-8 -*-

import os

import pytest
import torch
import torch.nn.functional as F

from fla.ops.gla import chunk_gla, fused_recurrent_gla
from fla.ops.gla.naive import naive_recurrent_gla
from fla.utils import device
from utils import assert_close

compiled_mode = os.getenv("COMPILER_MODE") == "1"
if compiled_mode:
    test_b_list = [1]
    test_t_list = [64]
    test_t_varlen_list = test_t_list
    test_d_list = [64, 128, 256]
    test_gate_list = [1.0]
else:
    test_b_list = [2]
    test_t_list = [1, 7, 15, 63, 286, 300]
    test_t_varlen_list = [1, 7, 15, 63, 286, 300, 1024]
    test_d_list = [50, 64, 100, 200, 256]
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
    T: int,
    H: int,
    D: int,
    dtype: torch.dtype
):
    torch.manual_seed(42)

    q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    g = F.logsigmoid(torch.randn((B, H, T, D), dtype=dtype, device=device)).requires_grad_()
    h0 = torch.randn(B, H, D, D, device=device).requires_grad_()

    do = torch.randn_like(v)
    dht = torch.randn_like(h0)
    ref, ref_ht = naive_recurrent_gla(
        q=q,
        k=k,
        v=v,
        gk=g,
        initial_state=h0,
        output_final_state=True
    )
    ((ref * do).sum() + (ref_ht * dht).sum()).backward()
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None
    ref_dh0, h0.grad = h0.grad.clone(), None

    tri, tri_ht = fused_recurrent_gla(
        q=q,
        k=k,
        v=v,
        gk=g,
        initial_state=h0,
        output_final_state=True
    )
    ((tri * do).sum() + (tri_ht * dht).sum()).backward()
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_dg, g.grad = g.grad.clone(), None
    tri_dh0, h0.grad = h0.grad.clone(), None

    assert_close("  o", ref, tri, 0.005)
    assert_close(" ht", ref_ht, tri_ht, 0.005)
    assert_close(" dq", ref_dq, tri_dq, 0.005)
    assert_close(" dk", ref_dk, tri_dk, 0.005)
    assert_close(" dv", ref_dv, tri_dv, 0.005)
    assert_close(" dg", ref_dg, tri_dg, 0.005)
    assert_close("dh0", ref_dh0, tri_dh0, 0.005)


@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("dtype", [torch.bfloat16])
@pytest.mark.parametrize("gate_logit_normalizer", test_gate_list)
@pytest.mark.parametrize("head_first", [True, False])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
def test_chunk(
    B: int,
    T: int,
    H: int,
    D: int,
    dtype: torch.dtype,
    gate_logit_normalizer: float,
    head_first: bool
):
    torch.manual_seed(42)
    os.environ['TRITON_F32_DEFAULT'] = 'ieee'
    # [B, H, T, D]
    if head_first:
        q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
        k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
        v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
        g = (F.logsigmoid(torch.randn((B, H, T, D), dtype=dtype, device=device)) / gate_logit_normalizer).requires_grad_()
    else:
        q = torch.randn((B, T, H, D), dtype=dtype, device=device).requires_grad_()
        k = torch.randn((B, T, H, D), dtype=dtype, device=device).requires_grad_()
        v = torch.randn((B, T, H, D), dtype=dtype, device=device).requires_grad_()
        g = (F.logsigmoid(torch.randn((B, T, H, D), dtype=dtype, device=device)) / gate_logit_normalizer).requires_grad_()
    h0 = torch.randn((B, H, D, D), dtype=dtype, device=device).requires_grad_()
    do = torch.randn_like(v)
    dht = torch.zeros((B, H, D, D), dtype=dtype, device=device)

    tri, tri_ht = chunk_gla(q, k, v, g, initial_state=h0, output_final_state=True, head_first=head_first)
    ((tri * do).sum() + (tri_ht * dht).sum()).backward()
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_dg, g.grad = g.grad.clone(), None
    tri_dh0, h0.grad = h0.grad.clone(), None

    ref, ref_ht = fused_recurrent_gla(q, k, v, g, initial_state=h0, output_final_state=True, head_first=head_first)
    ref, _ = fused_recurrent_gla(q, k, v, g, initial_state=h0, output_final_state=False, head_first=head_first)
    (ref * do).sum().backward()
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None
    ref_dh0, h0.grad = h0.grad.clone(), None

    assert_close("  o", ref, tri, 0.004)
    assert_close(" ht", ref_ht, tri_ht, 0.005)
    assert_close(" dq", ref_dq, tri_dq, 0.005)
    assert_close(" dk", ref_dk, tri_dk, 0.005)
    assert_close(" dv", ref_dv, tri_dv, 0.005)
    assert_close(" dg", ref_dg, tri_dg, 0.005)
    assert_close("dh0", ref_dh0, tri_dh0, 0.005)


@pytest.mark.parametrize("N", test_b_list)
@pytest.mark.parametrize("T", test_t_varlen_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("dtype", [torch.bfloat16, torch.float])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") is None,
    reason="Skipping test_chunk_varlen because SKIP_TEST_CHUNK_VARLEN is set"
)
def test_chunk_varlen(
    N: int,
    T: int,
    H: int,
    D: int,
    dtype: torch.dtype,
):
    torch.manual_seed(42)
    os.environ['TRITON_F32_DEFAULT'] = 'ieee'
    # randomly split the sequence into N segments
    offsets = torch.cat([
        torch.tensor([0], dtype=torch.long),
        torch.arange(16, T)[torch.randperm(T - 1)[:N-1]],
        torch.tensor([T], dtype=torch.long)
    ], 0).to(device).sort()[0]
    # seq-first required for inputs with variable lengths
    q = torch.randn((1, T, H, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((1, T, H, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((1, T, H, D), dtype=dtype, device=device).requires_grad_()
    g = F.logsigmoid(torch.randn((1, T, H, D), dtype=dtype, device=device)).requires_grad_()
    h0 = torch.randn((N, H, D, D), dtype=dtype, device=device).requires_grad_()
    do = torch.randn_like(v)

    ref, ref_ht = fused_recurrent_gla(
        q, k, v, g,
        initial_state=h0,
        output_final_state=True,
        cu_seqlens=offsets,
        head_first=False
    )
    ref, _ = fused_recurrent_gla(
        q, k, v, g,
        initial_state=h0,
        output_final_state=False,
        cu_seqlens=offsets,
        head_first=False
    )

    (ref * do).sum().backward()
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None
    ref_dh0, h0.grad = h0.grad.clone(), None

    tri, tri_ht = chunk_gla(
        q,
        k,
        v,
        g,
        initial_state=h0,
        output_final_state=True,
        cu_seqlens=offsets,
        head_first=False
    )
    ((tri * do).sum()).backward()
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_dg, g.grad = g.grad.clone(), None
    tri_dh0, h0.grad = h0.grad.clone(), None

    assert_close("  o", ref, tri, 0.004)
    assert_close(" ht", ref_ht, tri_ht, 0.005)
    assert_close(" dq", ref_dq, tri_dq, 0.005)
    assert_close(" dk", ref_dk, tri_dk, 0.005)
    assert_close(" dv", ref_dv, tri_dv, 0.005)
    assert_close(" dg", ref_dg, tri_dg, 0.005)
    assert_close("dh0", ref_dh0, tri_dh0, 0.005)
