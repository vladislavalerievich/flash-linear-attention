# -*- coding: utf-8 -*-

import os

import pytest
import torch
import torch.nn.functional as F

from fla.ops.gsa import chunk_gsa, fused_recurrent_gsa
from fla.ops.gsa.naive import naive_recurrent_gsa
from fla.utils import device, device_platform
from utils import assert_close

compiled_mode = os.getenv("COMPILER_MODE") == "1"
if compiled_mode:
    test_b_list = [1]
    test_t_list = [64]
    test_t_varlen_list = test_t_list
    test_d_list = [64, 128, 256]
    test_m_list = [32, 64, 128]
    test_gate_list = [1.0]
else:
    test_b_list = [2]
    test_t_list = [1, 7, 15, 63, 286, 300]
    test_t_varlen_list = [1, 7, 15, 63, 286, 300, 1024]
    test_d_list = [50, 64, 100, 200, 256]
    test_m_list = [32, 64, 128]
    test_gate_list = [1, 0.1, 10]
test_h_list = [2]


@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("M", test_m_list)
@pytest.mark.parametrize("head_first", [True, False])
@pytest.mark.parametrize("dtype", [torch.float])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
@pytest.mark.skipif(
    device_platform == 'intel',
    reason="Intel Triton Failure"
)
def test_fused_recurrent(
    B: int,
    T: int,
    H: int,
    D: int,
    M: int,
    head_first: bool,
    dtype: torch.dtype
):
    torch.manual_seed(42)

    q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
    s = torch.randn((B, H, T, M), dtype=dtype, device=device).requires_grad_()
    g = F.logsigmoid(torch.randn((B, H, T, M), dtype=dtype, device=device)).requires_grad_()
    hk0 = torch.randn(B, H, D, M, device=device).requires_grad_()
    hv0 = torch.randn(B, H, M, D, device=device).requires_grad_()

    do = torch.randn_like(v)
    ref, (ref_hkt, ref_hvt) = naive_recurrent_gsa(q, k, v, s, g, initial_state=(hk0, hv0), output_final_state=True)
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_ds, s.grad = s.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None
    ref_dhk0, hk0.grad = hk0.grad.clone(), None
    ref_dhv0, hv0.grad = hv0.grad.clone(), None

    tri, (tri_hkt, tri_hvt) = fused_recurrent_gsa(
        q=q if head_first else q.transpose(1, 2).contiguous(),
        k=k if head_first else k.transpose(1, 2).contiguous(),
        v=v if head_first else v.transpose(1, 2).contiguous(),
        s=s if head_first else s.transpose(1, 2).contiguous(),
        g=g if head_first else g.transpose(1, 2).contiguous(),
        initial_state=(hk0, hv0),
        output_final_state=True,
        head_first=head_first
    )
    tri, _ = fused_recurrent_gsa(
        q=q if head_first else q.transpose(1, 2).contiguous(),
        k=k if head_first else k.transpose(1, 2).contiguous(),
        v=v if head_first else v.transpose(1, 2).contiguous(),
        s=s if head_first else s.transpose(1, 2).contiguous(),
        g=g if head_first else g.transpose(1, 2).contiguous(),
        initial_state=(hk0, hv0),
        output_final_state=False,
        head_first=head_first
    )
    tri.backward(do if head_first else do.transpose(1, 2).contiguous())
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_ds, s.grad = s.grad.clone(), None
    tri_dg, s.grad = g.grad.clone(), None
    tri_dhk0, hk0.grad = hk0.grad.clone(), None
    tri_dhv0, hv0.grad = hv0.grad.clone(), None
    if not head_first:
        tri = tri.transpose(1, 2).contiguous()

    assert_close("   o", ref, tri, 0.005)
    assert_close(" hkt", ref_hkt, tri_hkt, 0.005)
    assert_close(" hvt", ref_hvt, tri_hvt, 0.005)
    assert_close("  dq", ref_dq, tri_dq, 0.005)
    assert_close("  dk", ref_dk, tri_dk, 0.005)
    assert_close("  dv", ref_dv, tri_dv, 0.005)
    assert_close("  ds", ref_ds, tri_ds, 0.005)
    assert_close("  dg", ref_dg, tri_dg, 0.005)
    assert_close("dhk0", ref_dhk0, tri_dhk0, 0.005)
    assert_close("dhv0", ref_dhv0, tri_dhv0, 0.005)


@pytest.mark.parametrize("N", test_b_list)
@pytest.mark.parametrize("T", test_t_varlen_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("M", test_m_list)
@pytest.mark.parametrize("dtype", [torch.float])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
@pytest.mark.skipif(
    device_platform == 'intel',
    reason="Intel Triton Failure"
)
def test_fused_recurrent_varlen(
    N: int,
    T: int,
    H: int,
    D: int,
    M: int,
    dtype: torch.dtype
):
    torch.manual_seed(42)
    os.environ['TRITON_F32_DEFAULT'] = 'ieee'
    # randomly split the sequence into N segments
    offsets = torch.cat([
        torch.tensor([0], dtype=torch.long),
        torch.arange(16, T)[torch.randperm(T - 1)[:N-1]],
        torch.tensor([T], dtype=torch.long)
    ], 0).to(device).sort()[0]

    q = torch.randn((1, T, H, D), dtype=dtype, device=device).requires_grad_()
    k = torch.randn((1, T, H, D), dtype=dtype, device=device).requires_grad_()
    v = torch.randn((1, T, H, D), dtype=dtype, device=device).requires_grad_()
    s = torch.randn((1, T, H, M), dtype=dtype, device=device).requires_grad_()
    g = F.logsigmoid(torch.randn((1, T, H, M), dtype=dtype, device=device)).requires_grad_()
    hk0 = torch.randn(N, H, D, M, device=device).requires_grad_()
    hv0 = torch.randn(N, H, M, D, device=device).requires_grad_()

    do = torch.randn_like(v)
    refs, ref_hkts, ref_hfts = [], [], []
    for i in range(N):
        ref, (ref_hkt, ref_hvt) = naive_recurrent_gsa(
            q[:, offsets[i]:offsets[i+1]].transpose(1, 2),
            k[:, offsets[i]:offsets[i+1]].transpose(1, 2),
            v[:, offsets[i]:offsets[i+1]].transpose(1, 2),
            s[:, offsets[i]:offsets[i+1]].transpose(1, 2),
            g[:, offsets[i]:offsets[i+1]].transpose(1, 2),
            initial_state=(hk0[i:i+1], hv0[i:i+1]),
            output_final_state=True
        )
        refs.append(ref.transpose(1, 2))
        ref_hkts.append(ref_hkt)
        ref_hfts.append(ref_hvt)
    ref = torch.cat(refs, 1)
    ref_hkt = torch.cat(ref_hkts, 0)
    ref_hvt = torch.cat(ref_hfts, 0)
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_ds, s.grad = s.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None
    ref_dhk0, hk0.grad = hk0.grad.clone(), None
    ref_dhv0, hv0.grad = hv0.grad.clone(), None

    tri, (tri_hkt, tri_hvt) = fused_recurrent_gsa(
        q=q,
        k=k,
        v=v,
        s=s,
        g=g,
        initial_state=(hk0, hv0),
        output_final_state=True,
        cu_seqlens=offsets,
        head_first=False
    )
    tri, _ = fused_recurrent_gsa(
        q=q,
        k=k,
        v=v,
        s=s,
        g=g,
        initial_state=(hk0, hv0),
        output_final_state=False,
        cu_seqlens=offsets,
        head_first=False
    )
    tri.backward(do)
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_ds, s.grad = s.grad.clone(), None
    tri_dg, s.grad = g.grad.clone(), None
    tri_dhk0, hk0.grad = hk0.grad.clone(), None
    tri_dhv0, hv0.grad = hv0.grad.clone(), None

    assert_close("   o", ref, tri, 0.005)
    assert_close(" hkt", ref_hkt, tri_hkt, 0.005)
    assert_close(" hvt", ref_hvt, tri_hvt, 0.005)
    assert_close("  dq", ref_dq, tri_dq, 0.005)
    assert_close("  dk", ref_dk, tri_dk, 0.005)
    assert_close("  dv", ref_dv, tri_dv, 0.005)
    assert_close("  ds", ref_ds, tri_ds, 0.005)
    assert_close("  dg", ref_dg, tri_dg, 0.005)
    assert_close("dhk0", ref_dhk0, tri_dhk0, 0.005)
    assert_close("dhv0", ref_dhv0, tri_dhv0, 0.005)


@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("M", test_m_list)
@pytest.mark.parametrize("dtype", [torch.float])
@pytest.mark.parametrize("gate_logit_normalizer", [1, 0.05, 20])
@pytest.mark.parametrize("head_first", [True, False])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
@pytest.mark.skipif(
    device_platform == 'intel',
    reason="Intel Triton Failure"
)
def test_chunk(
    B: int,
    H: int,
    T: int,
    D: int,
    M: int,
    dtype: torch.dtype,
    gate_logit_normalizer: float,
    head_first: bool
):
    torch.manual_seed(42)
    os.environ['TRITON_F32_DEFAULT'] = 'ieee'

    if head_first:
        q = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
        k = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
        v = torch.randn((B, H, T, D), dtype=dtype, device=device).requires_grad_()
        s = torch.randn((B, H, T, M), dtype=dtype, device=device).requires_grad_()
        g = (F.logsigmoid(torch.randn((B, H, T, M), dtype=dtype, device=device)) / gate_logit_normalizer).requires_grad_()
    else:
        q = torch.randn((B, T, H, D), dtype=dtype, device=device).requires_grad_()
        k = torch.randn((B, T, H, D), dtype=dtype, device=device).requires_grad_()
        v = torch.randn((B, T, H, D), dtype=dtype, device=device).requires_grad_()
        s = torch.randn((B, T, H, M), dtype=dtype, device=device).requires_grad_()
        g = (F.logsigmoid(torch.randn((B, T, H, M), dtype=dtype, device=device)) / gate_logit_normalizer).requires_grad_()
    hk0 = torch.randn(B, H, D, M, device=device).requires_grad_()
    hv0 = torch.randn(B, H, M, D, device=device).requires_grad_()

    do = torch.randn_like(v)
    ref, _ = fused_recurrent_gsa(q, k, v, s, g, initial_state=(hk0, hv0), head_first=head_first)
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_ds, s.grad = s.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None

    tri, _ = chunk_gsa(q, k, v, s, g, initial_state=(hk0, hv0), head_first=head_first)
    tri.backward(do)
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_ds, s.grad = s.grad.clone(), None
    tri_dg, s.grad = g.grad.clone(), None

    assert_close(" o", ref, tri, 0.005)
    assert_close("dq", ref_dq, tri_dq, 0.005)
    assert_close("dk", ref_dk, tri_dk, 0.005)
    assert_close("dv", ref_dv, tri_dv, 0.005)
    assert_close("ds", ref_ds, tri_ds, 0.008)
    assert_close("dg", ref_dg, tri_dg, 0.008)


@pytest.mark.parametrize("N", test_b_list)
@pytest.mark.parametrize("T", test_t_varlen_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("M", test_m_list)
@pytest.mark.parametrize("dtype", [torch.float])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") is None,
    reason="Skipping test_chunk_varlen because SKIP_TEST_CHUNK_VARLEN is set"
)
@pytest.mark.skipif(
    device_platform == 'intel',
    reason="Intel Triton Failure"
)
def test_chunk_varlen(
    N: int,
    T: int,
    H: int,
    D: int,
    M: int,
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
    s = torch.randn((1, T, H, M), dtype=dtype, device=device).requires_grad_()
    g = F.logsigmoid(torch.randn((1, T, H, M), dtype=dtype, device=device)).requires_grad_()
    hk0 = torch.randn(N, H, D, M, device=device).requires_grad_()
    hv0 = torch.randn(N, H, M, D, device=device).requires_grad_()
    do = torch.randn_like(v)

    ref, (ref_hkt, ref_hvt) = fused_recurrent_gsa(
        q, k, v, s, g,
        initial_state=(hk0, hv0),
        output_final_state=True,
        cu_seqlens=offsets,
        head_first=False
    )
    ref, _ = fused_recurrent_gsa(
        q, k, v, s, g,
        initial_state=(hk0, hv0),
        output_final_state=False,
        cu_seqlens=offsets,
        head_first=False
    )
    ref.backward(do)
    ref_dq, q.grad = q.grad.clone(), None
    ref_dk, k.grad = k.grad.clone(), None
    ref_dv, v.grad = v.grad.clone(), None
    ref_ds, s.grad = s.grad.clone(), None
    ref_dg, g.grad = g.grad.clone(), None
    ref_dhk0, hk0.grad = hk0.grad.clone(), None
    ref_dhv0, hv0.grad = hv0.grad.clone(), None

    tri, (tri_hkt, tri_hvt) = chunk_gsa(
        q, k, v, s, g,
        initial_state=(hk0, hv0),
        output_final_state=True,
        cu_seqlens=offsets,
        head_first=False
    )
    tri.backward(do)
    tri_dq, q.grad = q.grad.clone(), None
    tri_dk, k.grad = k.grad.clone(), None
    tri_dv, v.grad = v.grad.clone(), None
    tri_ds, s.grad = s.grad.clone(), None
    tri_dg, g.grad = g.grad.clone(), None
    tri_dhk0, hk0.grad = hk0.grad.clone(), None
    tri_dhv0, hv0.grad = hv0.grad.clone(), None

    assert_close("   o", ref, tri, 0.004)
    assert_close(" hkt", ref_hkt, tri_hkt, 0.005)
    assert_close(" hvt", ref_hvt, tri_hvt, 0.005)
    assert_close("  dq", ref_dq, tri_dq, 0.005)
    assert_close("  dk", ref_dk, tri_dk, 0.005)
    assert_close("  dv", ref_dv, tri_dv, 0.005)
    assert_close("  ds", ref_ds, tri_ds, 0.005)
    assert_close("  dg", ref_dg, tri_dg, 0.005)
    assert_close("dhk0", ref_dhk0, tri_dhk0, 0.005)
    assert_close("dhv0", ref_dhv0, tri_dhv0, 0.005)


@pytest.mark.parametrize("HQ", [8, 16])
@pytest.mark.parametrize("B", test_b_list)
@pytest.mark.parametrize("T", test_t_list)
@pytest.mark.parametrize("H", test_h_list)
@pytest.mark.parametrize("D", test_d_list)
@pytest.mark.parametrize("M", test_m_list)
@pytest.mark.parametrize("dtype", [torch.float])
@pytest.mark.skipif(
    os.getenv("SKIP_TEST_CHUNK_VARLEN") == "1",
    reason="Skipping test because TEST_CHUNK_VARLEN is enabled"
)
@pytest.mark.skipif(
    device_platform == 'intel',
    reason="Intel Triton Failure"
)
def test_inference(
    B: int,
    HQ: int,
    H: int,
    T: int,
    D: int,
    M: int,
    dtype: torch.dtype
):
    torch.manual_seed(42)

    q = torch.randn((B, HQ, T, D), dtype=dtype, device=device)
    k = torch.randn((B, H, T, D), dtype=dtype, device=device)
    v = torch.randn((B, H, T, D), dtype=dtype, device=device)
    s = torch.randn((B, H, T, M), dtype=dtype, device=device)
    g = F.logsigmoid(torch.randn((B, H, T, M), dtype=dtype, device=device))
    h0 = (torch.zeros(B, H, D, M, dtype=dtype, device=device),
          torch.zeros(B, H, M, D, dtype=dtype, device=device))

    ref, _ = naive_recurrent_gsa(q, k, v, s, g, initial_state=h0)
    tri = torch.empty_like(ref)
    for i in range(T):
        o, ht = fused_recurrent_gsa(
            q[:, :, i:i+1],
            k[:, :, i:i+1],
            v[:, :, i:i+1],
            s[:, :, i:i+1],
            g[:, :, i:i+1],
            initial_state=h0,
            output_final_state=True
        )
        tri[:, :, i] = o.squeeze(2)
        assert_close(f"o{i}", ref[:, :, i], tri[:, :, i], 0.005)
        h0 = ht
