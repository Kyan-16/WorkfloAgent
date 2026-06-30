"""
API 路由集成测试

使用 FastAPI TestClient 验证 HTTP 路由层：
- 路由是否正确注册
- 输入验证是否生效
- 错误响应格式是否正确
- 认证装饰器是否按预期工作
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


class MockCurrentUser:
    def __init__(self, role="admin", user_id="test-user", id=1, name="测试用户", department_id=1):
        self.role = role
        self.user_id = user_id
        self.id = id
        self.name = name
        self.department_id = department_id


@pytest.fixture
def app():
    """Build a minimal FastAPI app with routes registered"""
    from fastapi import FastAPI
    from ticket_agent.api.routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestPublicRoutes:
    """公开路由（无需认证）"""

    def test_list_categories(self, client):
        """分类列表是公开接口"""
        response = client.get("/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert len(data["categories"]) == 5

    def test_list_providers(self, client):
        """Provider 列表是公开接口"""
        response = client.get("/providers")
        assert response.status_code == 200
        data = response.json()
        assert "available_providers" in data


class TestAuthRequiredRoutes:
    """需要认证的路由"""

    def test_submit_ticket_requires_auth(self, client):
        """未认证的请求应返回 401"""
        response = client.post("/ticket", json={"content": "测试工单"})
        assert response.status_code == 401

    def test_knowledge_write_requires_auth(self, client):
        """知识库写入需要认证"""
        response = client.post("/knowledge", json={
            "content": "测试", "category": "IT",
        })
        assert response.status_code == 401

    def test_stats_requires_auth(self, client):
        """统计接口需要认证"""
        response = client.get("/stats")
        assert response.status_code == 401

    def test_feedback_requires_auth(self, client):
        """反馈接口需要认证"""
        response = client.post("/feedback", json={
            "ticket_id": "TK-001", "rating": 5, "feedback_type": "positive",
        })
        assert response.status_code == 401


class TestTicketRoutes:
    """工单路由集成测试"""

    def test_public_submit_ticket(self, client):
        """公开提票不需要认证"""
        # 数据层使用内存 SQLite
        from ticket_agent.database import init_db
        init_db(db_url="sqlite://")

        with patch(
            "ticket_agent.api.routes_ticket.get_coordinator"
        ) as mock_get_coord:
            mock_coord = AsyncMock()
            mock_coord.process.return_value = {
                "success": True, "ticket_id": "TK-001",
                "category": "IT", "response": "已为您处理：请尝试重启电脑。",
                "trace_id": "t1", "elapsed_seconds": 0.5,
                "agent_steps": [], "auto_resolved": True,
            }
            mock_get_coord.return_value = mock_coord

            response = client.post(
                "/api/ticket/public",
                json={"content": "电脑蓝屏了", "session_id": "test-session"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["ticket_id"] == "TK-001"


class TestKnowledgeRoutes:
    """知识库路由集成测试"""

    def test_list_knowledge_unauthorized(self, client):
        """未认证用户无法查看知识库"""
        response = client.get("/knowledge")
        assert response.status_code == 401
