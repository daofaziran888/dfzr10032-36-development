"""采集报告快照、更正回执、核销领取与监控对账的端到端测试。"""
from __future__ import annotations

from typing import Any

from app.services.report import BASELINE_DOWNLOAD_ID
from app.services.snapshot import build_package
from app.store import store

PERIOD = "2026-W47"
SOURCE = "北区"


def _download(client) -> dict[str, Any]:
    response = client.get("/api/report/snapshots/download", params={"period": PERIOD})
    assert response.status_code == 200, response.text
    assert response.headers["x-download-id"]
    assert "attachment" in response.headers["content-disposition"]
    return response.json()


def _correct(client, *, before: int = 21, after: int = 19, **extra: Any):
    payload = {"统计周期": PERIOD, "采集源": SOURCE, "更正前失败量": before, "更正后失败量": after, **extra}
    return client.post("/api/report/corrections", json={"values": payload})


def test_package_summary_matches_detail(client) -> None:
    package = _download(client)
    detail = package["明细"]
    assert detail and all(item["统计周期"] == PERIOD for item in detail)

    for summary in package["来源汇总"]:
        rows = [item for item in detail if item["采集源"] == summary["采集源"]]
        assert summary["记录数"] == len(rows)
        assert summary["成功量"] == sum(1 for item in rows if item["采集结果"] == "成功")
        assert summary["失败量"] == sum(1 for item in rows if item["采集结果"] == "失败")

    assert package["核对"]["一致"] is True
    assert all(item["一致"] for item in package["核对"]["来源核对"])
    assert package["合计"]["记录数"] == len(detail)
    assert package["合计"]["成功量"] + package["合计"]["失败量"] == len(detail)


def test_package_excludes_other_periods_and_rejects_unclassifiable_rows() -> None:
    """出包只收本周期；出现无法归类的采集结果时宁可失败，也不给出对不上的汇总。"""
    rows = [row for row in store.rows("report_result") if row["status"] == "已确认"]
    other_period = rows + [
        {**rows[0], "明细编号": "RES-X", "统计周期": "2026-W46", "采集源": "北区", "采集结果": "失败"}
    ]
    package = build_package(
        period=PERIOD, rows=other_period, download_id="SNPS-TEST-0001", generated_at="2026-11-20 00:00:00"
    )
    assert all(item["统计周期"] == PERIOD for item in package["明细"])
    assert all(item["明细编号"] != "RES-X" for item in package["明细"])
    assert package["核对"]["一致"] is True

    sample = next(row for row in rows if row["统计周期"] == PERIOD)
    unclassifiable = rows + [{**sample, "明细编号": "RES-Y", "采集结果": "未知"}]
    try:
        build_package(period=PERIOD, rows=unclassifiable, download_id="SNPS-TEST-0002", generated_at="2026-11-20 00:00:00")
    except ValueError as exc:
        assert "无法归类" in str(exc)
    else:  # pragma: no cover - 出包成功即为失败
        raise AssertionError("存在无法归类的采集结果仍然出包成功")


def test_download_requires_confirmed_results(client) -> None:
    response = client.get("/api/report/snapshots/download", params={"period": "2026-W01"})
    assert response.status_code == 400
    assert "没有已确认" in response.json()["detail"]

    bad_format = client.get("/api/report/snapshots/download", params={"period": "2026-47"})
    assert bad_format.status_code == 400


def test_snapshot_is_archived_and_retrievable_by_original_id(client) -> None:
    package = _download(client)
    download_id = package["快照标识"]

    listed = client.get("/api/report/snapshots").json()
    assert any(item["下载标识"] == download_id for item in listed["items"])

    fetched = client.get(f"/api/report/snapshots/{download_id}")
    assert fetched.status_code == 200
    assert fetched.json() == package
    assert fetched.json()["明细指纹"] == package["明细指纹"]


def test_correction_changes_effective_counts_once(client) -> None:
    package = _download(client)
    response = _correct(client, 下载标识=package["快照标识"])
    receipt = response.json()["entry"]
    assert response.json()["ok"] is True
    assert receipt["重复提交"] is False
    assert receipt["差额"] == -2
    assert receipt["应补差额"] == -2
    assert receipt["基础失败量"] == 21
    assert receipt["关联下载标识"] == package["快照标识"]
    assert len(receipt["影响明细"]) == 2

    north = [
        row
        for row in store.rows("report_result")
        if row["统计周期"] == PERIOD and row["采集源"] == SOURCE and row["采集结果"] == "失败"
    ]
    assert len(north) == 19


def test_duplicate_correction_does_not_deduct_twice(client) -> None:
    first = _correct(client).json()["entry"]
    second = _correct(client).json()["entry"]
    assert second["重复提交"] is True
    assert second["回执编号"] == first["回执编号"]

    north = [
        row
        for row in store.rows("report_result")
        if row["统计周期"] == PERIOD and row["采集源"] == SOURCE and row["采集结果"] == "失败"
    ]
    assert len(north) == 19
    assert len(client.get("/api/report/corrections").json()["items"]) == 1


def test_baseline_snapshot_still_shows_original_21(client) -> None:
    _download(client)
    _correct(client, 下载标识=BASELINE_DOWNLOAD_ID)

    original = client.get(f"/api/report/snapshots/{BASELINE_DOWNLOAD_ID}").json()
    north = next(item for item in original["来源汇总"] if item["采集源"] == SOURCE)
    assert north["失败量"] == 21
    assert original["明细指纹"] == client.get(f"/api/report/snapshots/{BASELINE_DOWNLOAD_ID}/file").json()["明细指纹"]

    fresh = _download(client)
    fresh_north = next(item for item in fresh["来源汇总"] if item["采集源"] == SOURCE)
    assert fresh_north["失败量"] == 19


def test_writeoff_then_booking_keeps_baseline_delta_and_batch(client) -> None:
    package = _download(client)
    receipt = _correct(client, 下载标识=package["快照标识"]).json()["entry"]

    writeoff = client.post(
        "/api/report/claims", json={"values": {"模式": "核销", "统计周期": PERIOD, "领取人": "北区结算员"}}
    ).json()
    assert writeoff["ok"] is True
    assert writeoff["核销条数"] == 2
    assert len(writeoff["台账"]) == 2
    assert {entry["回执编号"] for entry in writeoff["台账"]} == {receipt["回执编号"]}

    repeat = client.post(
        "/api/report/claims", json={"values": {"模式": "核销", "统计周期": PERIOD, "领取人": "北区结算员"}}
    ).json()
    assert repeat["核销条数"] == 0
    assert repeat["台账"] == []

    booking = client.post(
        "/api/report/claims", json={"values": {"模式": "入账", "统计周期": PERIOD, "领取人": "另一位结算员"}}
    ).json()
    assert booking["ok"] is True
    assert booking["核销条数"] == 0
    report = booking["报告"][0]
    assert report["基础失败量"] == 21
    assert report["可入账失败量"] == 19
    assert report["应补差额"] == -2

    linked = booking["回执"][0]
    assert linked["回执编号"] == receipt["回执编号"]
    assert linked["基础失败量"] == 21
    assert linked["应补差额"] == -2
    assert linked["核销批次"] == ["WOFF-20261120-01"] or linked["核销批次"]
    assert linked["核销条数"] == 2
    assert linked["核销人"] == ["北区结算员"]

    again = client.post(
        "/api/report/claims", json={"values": {"模式": "入账", "统计周期": PERIOD, "领取人": "另一位结算员"}}
    ).json()
    assert again["台账"] == []


def test_repeat_writeoff_claim_reports_existing_batches(client) -> None:
    """已经核销过的回执，再来领取时仍要带出基础数和已核销批次，而不是一片空白。"""
    receipt = _correct(client).json()["entry"]
    first = client.post(
        "/api/report/claims", json={"values": {"模式": "核销", "统计周期": PERIOD, "领取人": "北区结算员"}}
    ).json()
    assert first["核销条数"] == 2

    again = client.post(
        "/api/report/claims", json={"values": {"模式": "核销", "统计周期": PERIOD, "领取人": "北区结算员"}}
    ).json()
    assert again["message"] == "没有待核销的更正回执"
    assert again["台账"] == []
    shown = again["回执"][0]
    assert shown["回执编号"] == receipt["回执编号"]
    assert shown["基础失败量"] == 21
    assert shown["应补差额"] == -2
    assert shown["核销条数"] == 2
    assert shown["核销批次"] == first["核销批次"]


def test_booking_uses_archived_baseline_not_stale_report_row(client) -> None:
    """报告行上的失败量可能被改写，入账基础数应取交给各库核算时的快照。"""
    _download(client)
    _correct(client)
    for report in store.rows("report"):
        if report["统计周期"] == PERIOD and report["采集源"] == SOURCE:
            report["失败量"] = 999

    booking = client.post(
        "/api/report/claims", json={"values": {"模式": "入账", "统计周期": PERIOD, "领取人": "另一位结算员"}}
    ).json()
    north = next(item for item in booking["报告"] if item["采集源"] == SOURCE)
    assert north["基础失败量"] == 21
    assert north["可入账失败量"] == 19
    assert north["应补差额"] == -2


def test_monitor_consumes_snapshot_and_correction_with_trace(client) -> None:
    package = _download(client)
    receipt = _correct(client, 下载标识=package["快照标识"]).json()["entry"]

    snapshot_ack = client.post(
        "/api/monitor/reconciliation/snapshot", json={"values": {"下载标识": package["快照标识"]}}
    ).json()
    assert snapshot_ack["ok"] is True
    assert len(snapshot_ack["items"]) == len(package["来源汇总"])

    correction_ack = client.post(
        "/api/monitor/reconciliation/corrections",
        json={"values": {"统计周期": PERIOD, "更正批次": receipt["更正批次"]}},
    ).json()
    assert correction_ack["ok"] is True
    assert len(correction_ack["items"]) == 1

    rows = client.get("/api/monitor/reconciliation", params={"download_id": package["快照标识"]}).json()["items"]
    assert {row["原统计周期"] for row in rows} == {PERIOD}
    correction_rows = [row for row in rows if row["类型"] == "更正"]
    assert len(correction_rows) == 1
    assert correction_rows[0]["更正批次"] == receipt["更正批次"]
    assert correction_rows[0]["回执编号"] == receipt["回执编号"]
    assert correction_rows[0]["基础失败量"] == 21
    assert correction_rows[0]["更正后失败量"] == 19
    assert correction_rows[0]["差额"] == -2

    repeat = client.post(
        "/api/monitor/reconciliation/corrections",
        json={"values": {"统计周期": PERIOD, "更正批次": receipt["更正批次"]}},
    ).json()
    assert repeat["items"] == []
    assert repeat["ok"] is True


def test_monitor_rejects_unknown_download_id(client) -> None:
    response = client.post("/api/monitor/reconciliation/snapshot", json={"values": {"下载标识": "SNPS-NONE"}})
    assert response.json()["ok"] is False
    assert "不存在" in response.json()["message"]


def test_correction_rejects_inconsistent_baseline(client) -> None:
    response = _correct(client, before=20, after=19)
    payload = response.json()
    assert payload["ok"] is False
    assert "不一致" in payload["message"]
    assert client.get("/api/report/corrections").json()["total"] == 0
