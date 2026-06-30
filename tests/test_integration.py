"""
集成测试 — Coordinator + Tools + Feedback + Evolution + API

这些测试使用 Mock LLM，不依赖外部 API，可离线运行。
覆盖核心业务流程和 P0/P1/P2 新增功能。
"""
import os
import json
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Note: 不在这里全局设置 AGENT_TRACE_ENABLED，避免影响其他测试文件。


# ===== Fixtures =====

@pytest.fixture
def mock_llm():
    """Mock LLM — 返回预设响应，不调用真实 API"""
    llm = MagicMock()
    llm.model = "mock-model"

    async def generate(messages, **kwargs):
        from llm.base import LLMResponse
        last_msg = messages[-1].content if messages else ""
        return LLMResponse(
            content=f"Mock回复: {last_msg[:50]}",
            model="mock-model",
            tool_calls=[],
        )
    llm.generate = generate
    return llm


@pytest.fixture
def ticket_repo():
    """清空工单仓库，确保测试隔离"""
    from ticket_agent.repository import get_ticket_repository
    repo = get_ticket_repository()
    # 使用内存 SQLite 确保隔离
    from ticket_agent.database import init_db
    init_db(db_url="sqlite://")
    return repo


@pytest.fixture
def coordinator(mock_llm):
    """构建 Coordinator 实例"""
    from ticket_agent.coordinator.linear import LinearCoordinator
    return LinearCoordinator(
        llm=mock_llm,
        rag_top_k=3,
        max_tool_rounds=2,
    )


# ===== Coordinator 集成测试 =====

class TestCoordinatorIntegration:
    """测试完整工单处理流程"""

    @pytest.mark.asyncio
    async def test_process_basic_ticket(self, coordinator):
        """基本工单处理流程"""
        result = await coordinator.process(
            user_input="我的电脑蓝屏了",
            session_id="test_sess_001",
        )
        assert result["success"] is True
        assert "ticket_id" in result
        assert result["ticket_id"].startswith("TK-")
        assert result["category"] in ["IT", "HR", "财务", "运维", "其他"]
        assert len(result["response"]) > 0
        assert len(result["agent_steps"]) > 0

    @pytest.mark.asyncio
    async def test_process_hr_ticket(self, coordinator):
        """HR 工单处理"""
        result = await coordinator.process(
            user_input="我要请三天年假，下周一到周三",
            session_id="test_sess_002",
        )
        assert result["success"] is True
        # HR 工单需要审批
        assert result["category"] in ["HR", "其他"]

    @pytest.mark.asyncio
    async def test_process_finance_ticket(self, coordinator):
        """财务工单处理"""
        result = await coordinator.process(
            user_input="报销上周出差费用，上海两晚住宿",
            session_id="test_sess_003",
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_process_empty_input(self, coordinator):
        """空输入处理"""
        result = await coordinator.process(
            user_input="",
            session_id="test_sess_empty",
        )
        # 系统不应崩溃
        assert "success" in result

    @pytest.mark.asyncio
    async def test_agent_steps_contain_all_phases(self, coordinator):
        """Agent 执行步骤完整"""
        result = await coordinator.process(
            user_input="VPN 连不上了，帮忙看看",
            session_id="test_sess_steps",
        )
        steps = {s["step"] for s in result["agent_steps"]}
        assert "classify" in steps
        # IT 工单应该有 retrieve 步骤
        if result["category"] == "IT":
            assert "retrieve" in steps

    @pytest.mark.asyncio
    async def test_process_with_real_retriever(self, coordinator):
        """使用真实 RAG 检索器的端到端流程测试"""
        # 注入一个真实的 KeywordRetriever
        from rag.retriever import KeywordRetriever
        retriever = KeywordRetriever(
            documents=[
                {"content": "VPN 故障排查：1. 检查网络连接 2. 重新安装客户端 3. 联系IT部门", "metadata": {"source": "kb"}},
                {"content": "电脑蓝屏解决方法：1. 重启电脑 2. 更新驱动 3. 系统还原", "metadata": {"source": "kb"}},
            ],
            top_k=3,
        )
        coordinator.retriever = retriever

        result = await coordinator.process(
            user_input="VPN 连接失败，无法访问公司内网资源",
            session_id="test_real_retriever",
        )
        assert result["success"] is True
        assert "ticket_id" in result
        assert result["ticket_id"].startswith("TK-")

        step_names = {s["step"] for s in result["agent_steps"]}
        assert "classify" in step_names

    @pytest.mark.asyncio
    async def test_process_human_escalation(self, coordinator):
        """测试需转人工的场景"""
        result = await coordinator.process(
            user_input="我很生气！叫你们经理来！我要投诉！",
            session_id="test_escalation",
        )
        assert result["success"] is True
        assert "response" in result

    @pytest.mark.asyncio
    async def test_process_with_images(self, coordinator):
        """测试带图片的工单处理"""
        result = await coordinator.process(
            user_input="电脑蓝屏了，请看截图",
            session_id="test_images",
            images=["http://example.com/screenshot.png"],
        )
        assert result["success"] is True


# ===== 工具集成测试 =====

class TestTicketTools:
    """测试数据库驱动的工单工具"""

    @pytest.mark.asyncio
    async def test_get_ticket_status_not_found(self):
        """查询不存在的工单"""
        from ticket_agent.tools.ticket_tools import GetTicketStatusTool
        tool = GetTicketStatusTool()
        result = await tool.execute(ticket_id="TK-NONEXISTENT")
        assert result.success is False
        assert "不存在" in (result.error or "")

    @pytest.mark.asyncio
    async def test_create_then_get_ticket(self, ticket_repo):
        """创建工单后查询"""
        from ticket_agent.models.ticket import Ticket, TicketCategory
        ticket = Ticket(
            content="测试工单",
            user_id="test_user",
            category=TicketCategory.IT,
        )
        ticket_repo.create(ticket)

        from ticket_agent.tools.ticket_tools import GetTicketStatusTool
        tool = GetTicketStatusTool()
        result = await tool.execute(ticket_id=ticket.ticket_id)
        assert result.success is True
        data = json.loads(result.output)
        assert data["content"] == "测试工单"
        assert data["user_id"] == "test_user"

    @pytest.mark.asyncio
    async def test_update_ticket(self, ticket_repo):
        """更新工单字段"""
        from ticket_agent.models.ticket import Ticket
        ticket = Ticket(content="待更新工单", user_id="test_user")
        ticket_repo.create(ticket)

        from ticket_agent.tools.ticket_tools import UpdateTicketTool
        tool = UpdateTicketTool()
        result = await tool.execute(
            ticket_id=ticket.ticket_id,
            field="status",
            value="处理中",
        )
        assert result.success is True

        # 验证更新结果
        updated = ticket_repo.get(ticket.ticket_id)
        assert updated.status.value == "处理中"  # noqa

    @pytest.mark.asyncio
    async def test_escalate_ticket(self, ticket_repo):
        """转人工"""
        from ticket_agent.models.ticket import Ticket
        ticket = Ticket(content="需转人工的工单", user_id="test_user")
        ticket_repo.create(ticket)

        from ticket_agent.tools.ticket_tools import EscalateToHumanTool
        tool = EscalateToHumanTool()
        result = await tool.execute(
            ticket_id=ticket.ticket_id,
            reason="用户投诉",
            priority="high",
        )
        assert result.success is True
        assert "已转人工" in result.output

    @pytest.mark.asyncio
    async def test_update_invalid_field(self):
        """更新不存在的字段"""
        from ticket_agent.tools.ticket_tools import UpdateTicketTool
        tool = UpdateTicketTool()
        result = await tool.execute(
            ticket_id="TK-001",
            field="invalid_field",
            value="test",
        )
        assert result.success is False


# ===== 反馈系统集成测试 =====

class TestFeedbackSystem:
    """测试反馈系统"""

    def setup_method(self):
        from ticket_agent.database import init_db
        init_db(db_url="sqlite://")

    def test_feedback_store_crud(self):
        """反馈存储 CRUD"""
        from ticket_agent.feedback.store import get_feedback_store, TicketFeedback, reset_feedback_store
        reset_feedback_store()
        store = get_feedback_store()
        fb = TicketFeedback(
            ticket_id="TK-FB-001",
            user_id="test_user",
            rating=4,
            feedback_type="positive",
            comment="处理得很好",
        )
        saved = store.add(fb)
        assert saved.feedback_id == fb.feedback_id

        fetched = store.get(fb.feedback_id)
        assert fetched is not None
        assert fetched.rating == 4

        by_ticket = store.get_by_ticket("TK-FB-001")
        assert by_ticket is not None

    def test_feedback_stats(self):
        """反馈统计"""
        from ticket_agent.feedback.store import get_feedback_store, TicketFeedback, reset_feedback_store
        reset_feedback_store()
        store = get_feedback_store()
        store.add(TicketFeedback(ticket_id="TK-S1", user_id="u1", rating=5, feedback_type="positive"))
        store.add(TicketFeedback(ticket_id="TK-S2", user_id="u2", rating=1, feedback_type="negative"))
        store.add(TicketFeedback(ticket_id="TK-S3", user_id="u3", rating=3, feedback_type="neutral"))

        stats = store.get_stats()
        assert stats["total"] == 3
        assert stats["positive"] == 1
        assert stats["negative"] == 1
        assert stats["neutral"] == 1
        assert 2.5 < stats["avg_rating"] < 3.5

        positive_list = store.list_all(feedback_type="positive")
        assert len(positive_list) == 1


# ===== 模式提取集成测试 =====

class TestPatternExtraction:
    """测试工单模式提取"""

    def setup_method(self):
        from ticket_agent.database import init_db
        init_db(db_url="sqlite://")

    @pytest.mark.asyncio
    async def test_lightweight_extraction(self):
        """轻量模式提取"""
        from ticket_agent.memory.pattern_extractor import PatternExtractor

        extractor = PatternExtractor(llm=None)
        pattern = await extractor.extract({
            "ticket_id": "TK-PAT-001",
            "category": "IT",
            "content": "电脑蓝屏，无法开机",
            "solution": "重启进入安全模式，运行内存诊断",
            "tool_calls": ["get_ticket_status"],
        })
        assert pattern is not None
        assert pattern.category == "IT"
        assert len(pattern.keywords) > 0

    def test_pattern_search(self):
        """模式搜索"""
        import tempfile, os
        from ticket_agent.memory.pattern_extractor import PatternExtractor, PatternStore, TicketPattern

        # 使用临时文件隔离
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("[]")
            tmp = f.name
        store = PatternStore(db_path=tmp)
        store.save(TicketPattern(
            pattern_id="pat_test_001",
            category="IT",
            problem_summary="电脑蓝屏",
            solution="重启进安全模式",
            keywords=["蓝屏", "重启", "电脑"],
            confidence=0.8,
            frequency=3,
        ))

        extractor = PatternExtractor()
        # 用 store 的内部方法直接测试
        matched = store.search("IT", ["电脑", "蓝屏"], top_k=3)
        assert len(matched) > 0
        assert matched[0].problem_summary == "电脑蓝屏"
        os.unlink(tmp)


# ===== 进化系统集成测试 =====

class TestEvolutionSystem:
    """测试自进化系统"""

    def setup_method(self):
        from ticket_agent.database import init_db
        init_db(db_url="sqlite://")

    @pytest.mark.asyncio
    async def test_ticket_review_rule_based(self):
        """基于规则的工单复盘"""
        from ticket_agent.evolution.reviewer import TicketReviewer

        reviewer = TicketReviewer(llm=None)
        review = await reviewer.review_ticket({
            "ticket_id": "TK-REV-001",
            "category": "IT",
            "content": "VPN 连不上",
            "response": "请检查网络连接...",
            "rag_doc_count": 2,
            "tool_calls": ["get_ticket_status"],
        })
        assert review is not None
        assert 0 <= review.overall_score <= 1
        assert "suggestions" in review.__dict__

    def test_accuracy_tracker(self):
        """分类准确率追踪"""
        import os, tempfile
        from ticket_agent.evolution.accuracy_tracker import AccuracyTracker, AccuracyStore

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("[]")
            tmp = f.name
        store = AccuracyStore(db_path=tmp)
        tracker = AccuracyTracker()
        tracker.store = store
        tracker.record_correction(
            ticket_id="TK-ACC-001",
            agent_category="IT",
            human_category="IT",
            confidence=0.95,
        )
        tracker.record_correction(
            ticket_id="TK-ACC-002",
            agent_category="IT",
            human_category="运维",
            confidence=0.6,
        )

        stats = tracker.get_overall_accuracy()
        assert stats["total"] == 2
        assert stats["correct"] == 1
        assert stats["accuracy"] == 0.5

    @pytest.mark.asyncio
    async def test_knowledge_gap_detection(self):
        """知识缺口检测"""
        import os, tempfile
        from ticket_agent.evolution.knowledge_gap import KnowledgeGapDetector, GapStore

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("[]")
            tmp = f.name
        store = GapStore(db_path=tmp)
        detector = KnowledgeGapDetector(llm=None)
        detector.store = store
        gap = await detector.detect_gap({
            "ticket_id": "TK-GAP-001",
            "category": "运维",
            "content": "Kubernetes 集群节点 NotReady",
            "rag_doc_count": 0,
        })
        assert gap is not None
        assert gap.category == "运维"
        assert gap.frequency == 1
        os.unlink(tmp)

    def test_accuracy_confusion_matrix(self):
        """混淆矩阵分析"""
        import os, tempfile
        from ticket_agent.evolution.accuracy_tracker import AccuracyTracker, AccuracyStore

        # 使用临时文件隔离
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("[]")
            tmp = f.name
        store = AccuracyStore(db_path=tmp)
        tracker = AccuracyTracker()
        tracker.store = store  # 使用隔离的 store

        tracker.record_correction("TK-CF-01", "IT", "运维", 0.7)
        tracker.record_correction("TK-CF-02", "IT", "运维", 0.65)
        tracker.record_correction("TK-CF-03", "财务", "HR", 0.8)

        pairs = tracker.get_confusion_pairs()
        assert len(pairs) >= 2
        it_ops = [p for p in pairs if p["agent_category"] == "IT" and p["human_category"] == "运维"]
        assert len(it_ops) == 1
        assert it_ops[0]["count"] == 2
        os.unlink(tmp)
