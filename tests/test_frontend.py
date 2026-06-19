import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app


class FakeEngine:
    is_ready = False


@pytest.mark.anyio
async def test_frontend_console_is_served() -> None:
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine()))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        index_response = await client.get("/")
        js_response = await client.get("/static/app.js")
        css_response = await client.get("/static/styles.css")

    assert index_response.status_code == 200
    assert "PaddleOCR LAN Console" in index_response.text
    assert "历史记录" in index_response.text
    assert "设置" in index_response.text
    assert "下载 JSON" in index_response.text
    assert "复制文本" in index_response.text
    assert 'data-ui-kit="shadcn-ui"' in index_response.text
    assert "保留清理" in index_response.text
    assert "访问日志" in index_response.text
    assert js_response.status_code == 200
    assert "refreshHealth" in js_response.text
    assert "deleteJob" in js_response.text
    assert "retryJob" in js_response.text
    assert "saveSettings" in js_response.text
    assert "runRetentionCleanup" in js_response.text
    assert css_response.status_code == 200
    assert "--background" in css_response.text
    assert ".tabs-list" in css_response.text
    assert ".badge" in css_response.text
