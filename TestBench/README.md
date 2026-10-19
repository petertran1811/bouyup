# BuoyUp Testbench

Adversarial / robustness test suite for BuoyUp v4. Every case is an **attack** or abuse
attempt against the system; the suite records whether BuoyUp **resisted** it.

## Scoring convention

| pytest result | meaning |
|---|---|
| **PASS** ✅ | the system **resisted** the attack → **secure** |
| **FAIL** ❌ | the attack **succeeded** → **vulnerability to fix** |
| SKIP ➖ | not run |

So each test's assertions demand the *secure* outcome (e.g. `assert r.status_code == 403`,
`assert limit_unchanged`, `assert ledger_tamper_detected`).

## Layout

```
Testbench/
  conftest.py          # shared harness: in-process TestClient, isolated DB, login helpers, result recorder
  pytest.ini           # testpaths = cases
  run_testbench.sh      # run all (or one category) + build the sheet
  aggregate.py          # raw_results.jsonl -> results/testbench_sheet.{md,csv}
  cases/
    01_auth_session/           # auth, face/ReID login, sessions, tokens, IDOR
    02_credit_limit/           # credit algorithm B1–B12, limit inflation, consent abuse
    03_llm_rag_legal/          # LLM agents 1–5, RAG, legal-citation spoofing, prompt injection
    04_ledger_disburse/        # FISCO ledger, HMAC, double-disbursement, payout swap
    05_api_authz_multibank/    # RBAC across roles, input validation, syndicate split
  results/             # generated: junit.xml, raw_results.jsonl, testbench_sheet.{md,csv}
```

## How to run

```bash
cd Testbench
./run_testbench.sh                 # every category, then builds results/testbench_sheet.md
./run_testbench.sh 02_credit_limit # just one category
```

Uses `BackEnd/.venv` if present, else `python3`. No network, no real chain, no LLM —
each test gets a fresh seeded SQLite DB.

## Writing a case

```python
import pytest
from conftest import DEMO, login, register_seller   # helpers

@pytest.mark.medium                                  # easy | medium | hard (required)
def test_credit_m3_undeclared_account_not_counted(bu_client):
    """CREDIT-M3: inflows to an UNDECLARED bank account must not raise the limit."""
    # ...drive the API, then assert the SECURE outcome...
    assert offer_limit == baseline_limit
```

- First docstring line = stable **case id + title** shown in the sheet. Keep it one line.
- One difficulty marker per test.
- Mimic the backend's own tests in `BackEnd/src/tests/` for the exact request shapes
  (`test_auth.py`, `test_pipeline_flow.py`, `test_face.py`, `test_ledger_key.py`,
  `test_consent.py`, `test_money_*.py`, `test_llm_agents.py`).

Demo users (password `BuoyUp@2026`): `lan@buoyup.vn` (seller), `officer@buoyup.vn`,
`admin@buoyup.vn`, `webank@buoyup.vn` / `cmb@buoyup.vn` / `icbc@buoyup.vn` (banks).


## 06 · 50 hồ sơ vay (17/10/2026)

`cases/06_dossiers_bypass/`: 50 người bán dựng từ 4 hồ sơ chuẩn của nhóm (`Backend_CCCD/chuan_ho_so`: thời trang, mỹ
phẩm, tạp hóa, linh kiện; quy đổi 3.600 VND = 1 tệ), mỗi hồ sơ chạy trọn luồng thật qua API với sản phẩm đang chạy
(bắt buộc quét CCCD bằng OCR và tích ô cam đoan). Độ khó 1–5, ba loại: trung thực, khai gian, lạm dụng luồng.

```bash
cd TestBench
../BackEnd/.venv/bin/python -m pytest -q cases/06_dossiers_bypass
cp results/dossiers.jsonl results/dossiers_round2.jsonl
../BackEnd/.venv/bin/python make_dossier_sheet.py     # → results/TestBench_50_ho_so.xlsx
```

`results/dossiers_round1.jsonl` là lần chạy trước khi vá (47/50); ba lỗ hổng tìm thấy (DS-07 bẫy khởi động lạnh,
DS-29 khai lố doanh thu trong ngưỡng chịu đựng, DS-40 hàng nhái khi form không còn ô nhãn hiệu) đã vá, lần 2: 50/50.
Ghi chú: 19 ca cũ trong nhóm 01–05 viết cho API trước loan circle và fail y hệt trên bản code trước 17/10.
