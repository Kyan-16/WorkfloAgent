"""
演示数据生成器

生成完整的企业场景演示数据，涵盖：
- 各角色用户（员工/工程师/经理/管理员）
- 大量真实风格工单（IT/HR/财务/运维）
- 工单处理模式
- 用户反馈
- 复盘记录
- 知识缺口

运行方式：
    python -m ticket_agent.database.seed_demo
"""
import json
import os
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_demo")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════
# 工单数据（写入 SQLite / MySQL）
# ═══════════════════════════════════════════════════════════

SAMPLE_TICKETS = [
    # ── IT 工单 ──
    {"ticket_id": "TK-DEMO-001", "user_id": "zhangsan", "user_name": "张三",
     "content": "电脑蓝屏了，错误码 0x0000001A，开机就蓝屏无法进入系统，工号 TK-001",
     "category": "IT", "status": "已解决", "priority": "high", "department_id": 1,
     "assigned_to": 3, "assigned_name": "赵工",
     "agent_response": "您好，已查到工单 TK-001。根据知识库中的 Windows 蓝屏排查步骤，建议您：1. 重启按 F8 进入安全模式 2. 运行内存诊断工具 3. 检查最近是否安装新驱动。已更新工单状态为'处理中'。"},
    {"ticket_id": "TK-DEMO-002", "user_id": "zhangsan", "user_name": "张三",
     "content": "VPN 连不上了，提示'连接超时'，之前一直正常使用",
     "category": "IT", "status": "已解决", "priority": "high", "department_id": 1,
     "assigned_to": 4, "assigned_name": "王工",
     "agent_response": "您好，VPN 连接超时通常由以下原因引起：1. 检查本地网络是否正常 2. 重启 VPN 客户端 3. 检查配置文件是否过期。已为您重置 VPN 配置。"},
    {"ticket_id": "TK-DEMO-003", "user_id": "zhangsan", "user_name": "张三",
     "content": "申请开通一个 FTP 账号给外包团队使用，需要只读权限",
     "category": "IT", "status": "待处理", "priority": "low", "department_id": 1},
    {"ticket_id": "TK-DEMO-004", "user_id": "lisi", "user_name": "李四",
     "content": "邮箱密码忘记了，登录不了 Outlook，需要重置密码",
     "category": "IT", "status": "处理中", "priority": "normal", "department_id": 1,
     "assigned_to": 3, "assigned_name": "赵工"},
    {"ticket_id": "TK-DEMO-005", "user_id": "lisi", "user_name": "李四",
     "content": "电脑运行特别慢，C 盘空间只剩 2GB 了，帮忙清理一下",
     "category": "IT", "status": "已解决", "priority": "normal", "department_id": 1,
     "assigned_to": 4, "assigned_name": "王工",
     "agent_response": "好的，针对 C 盘空间不足的问题：1. 已清理临时文件释放了 15GB 空间 2. 已将大文件迁移到 D 盘 3. 建议定期使用磁盘清理工具。"},
    {"ticket_id": "TK-DEMO-006", "user_id": "wangwu", "user_name": "王五",
     "content": "公司配的笔记本电脑屏幕出现坏点了，右下角一个亮点，需要维修",
     "category": "IT", "status": "待处理", "priority": "normal", "department_id": 1},
    {"ticket_id": "TK-DEMO-007", "user_id": "admin", "user_name": "系统管理员",
     "content": "需要安装 Project 2019 专业版用于项目管理，已有授权码",
     "category": "IT", "status": "已解决", "priority": "low", "department_id": 1,
     "assigned_to": 3, "assigned_name": "赵工",
     "agent_response": "已收到软件安装申请。根据 IT 软件安装流程，需要 1-2 个工作日审批。请确保软件仅用于公司业务用途。已创建安装任务。"},

    # ── HR 工单 ──
    {"ticket_id": "TK-DEMO-008", "user_id": "zhangsan", "user_name": "张三",
     "content": "请三天年假，下周一至周三，家里有事需处理",
     "category": "HR", "status": "待审批", "priority": "normal", "department_id": 2,
     "needs_approval": True, "approval_status": "pending"},
    {"ticket_id": "TK-DEMO-009", "user_id": "wangwu", "user_name": "王五",
     "content": "查一下我今年的剩余年假天数，去年入职的应该还有 5 天",
     "category": "HR", "status": "已解决", "priority": "normal", "department_id": 2,
     "assigned_to": 7, "assigned_name": "赵专员",
     "agent_response": "您好，经查询：您的入职日期为 2023 年 7 月，当前年假余额为 5 天。您今年已使用 2 天（春节+清明），剩余 3 天。建议在年底前安排休假。"},
    {"ticket_id": "TK-DEMO-010", "user_id": "lisi", "user_name": "李四",
     "content": "想了解一下公司对硕士在职教育的补贴政策，想报个在职研究生",
     "category": "HR", "status": "已解决", "priority": "low", "department_id": 2,
     "assigned_to": 7, "assigned_name": "赵专员",
     "agent_response": "公司教育补贴政策如下：1. 与岗位相关的在职教育可申请 50% 学费补贴（上限 3 万元/年）2. 需提前报备 HR 审批 3. 毕业后需在公司服务满 2 年。详情可咨询 HR 王经理。"},

    # ── 财务工单 ──
    {"ticket_id": "TK-DEMO-011", "user_id": "lisi", "user_name": "李四",
     "content": "报销上周北京出差费用：高铁往返 1100 元，住宿两晚 900 元，市内交通 200 元，共 2200 元",
     "category": "财务", "status": "待审批", "priority": "normal", "department_id": 3,
     "needs_approval": True, "approval_status": "pending"},
    {"ticket_id": "TK-DEMO-012", "user_id": "zhangsan", "user_name": "张三",
     "content": "查询我 3 月份提交的团建报销进度，已经两个月了还没到账",
     "category": "财务", "status": "已解决", "priority": "high", "department_id": 3,
     "assigned_to": 10, "assigned_name": "刘专员",
     "agent_response": "您好，经查询：您 3 月 15 日提交的团建报销（TK-20240315-XX）已于 4 月 20 日通过财务审核，将于本月 30 日统一打款。如有疑问请联系财务刘专员。"},
    {"ticket_id": "TK-DEMO-013", "user_id": "wangwu", "user_name": "王五",
     "content": "申请开具一张增值税专用发票，抬头信息：某某科技有限公司，税号 91440101MA5XXXX",
     "category": "财务", "status": "处理中", "priority": "normal", "department_id": 3,
     "assigned_to": 10, "assigned_name": "刘专员"},

    # ── 运维工单 ──
    {"ticket_id": "TK-DEMO-014", "user_id": "admin", "user_name": "系统管理员",
     "content": "【紧急】线上服务器 502 Bad Gateway，用户反馈无法访问首页，请立即排查！",
     "category": "运维", "status": "已解决", "priority": "urgent", "department_id": 4,
     "assigned_to": 12, "assigned_name": "李工",
     "agent_response": "已收到 P0 告警！正在排查：1. 检查 Nginx 状态正常 2. 发现后端服务进程挂掉 3. 已重新启动服务 4. 监控指标恢复正常。根因：内存泄漏导致 OOM。已创建跟进工单。"},
    {"ticket_id": "TK-DEMO-015", "user_id": "admin", "user_name": "系统管理员",
     "content": "MySQL 数据库查询特别慢，慢查询日志显示一些 SQL 执行超过 10 秒",
     "category": "运维", "status": "处理中", "priority": "high", "department_id": 4,
     "assigned_to": 12, "assigned_name": "李工"},
    {"ticket_id": "TK-DEMO-016", "user_id": "admin", "user_name": "系统管理员",
     "content": "需要部署一套新的 Redis 集群，3 主 3 从，用于缓存优化",
     "category": "运维", "status": "待处理", "priority": "normal", "department_id": 4},

    # ── 转人工示例 ──
    {"ticket_id": "TK-DEMO-017", "user_id": "zhangsan", "user_name": "张三",
     "content": "我要投诉！隔壁部门的人一直占用会议室不提前预约，已经好几次了，请处理",
     "category": "其他", "status": "已转人工", "priority": "normal", "department_id": 1,
     "agent_response": "您好，已收到您的投诉工单。根据评估，您的问题需要转交人工客服处理。我们将尽快安排专人与您联系。"},

    # ── 更多已解决的工单 ──
    {"ticket_id": "TK-DEMO-018", "user_id": "lisi", "user_name": "李四",
     "content": "企业微信收不到消息通知了，电脑端和手机端都不行",
     "category": "IT", "status": "已解决", "priority": "normal", "department_id": 1,
     "assigned_to": 4, "assigned_name": "王工",
     "agent_response": "企业微信通知问题排查：1. 检查系统通知权限是否开启 2. 企业微信内'接收消息通知'是否开启 3. 已远程帮您重置通知配置，请重新登录试试。"},
    {"ticket_id": "TK-DEMO-019", "user_id": "wangwu", "user_name": "王五",
     "content": "打印机无法连接，驱动显示错误代码 0x00000709",
     "category": "IT", "status": "已解决", "priority": "normal", "department_id": 1,
     "assigned_to": 3, "assigned_name": "赵工",
     "agent_response": "打印机驱动错误处理：已远程删除旧的打印机驱动并重新安装最新版本，现在可以正常打印了。建议以后使用公司统一打印管理平台。"},
    {"ticket_id": "TK-DEMO-020", "user_id": "zhangsan", "user_name": "张三",
     "content": "申请开通 GitLab 项目权限，项目名称为 data-platform，需要 maintainer 权限",
     "category": "IT", "status": "已解决", "priority": "low", "department_id": 1,
     "assigned_to": 4, "assigned_name": "王工",
     "agent_response": "已为您开通 GitLab data-platform 项目的 maintainer 权限。请使用公司邮箱登录，如有问题请联系 IT 部门。"},
    {"ticket_id": "TK-DEMO-021", "user_id": "lisi", "user_name": "李四",
     "content": "想了解公司对员工考勤的迟到政策，每个月几次以内是允许的",
     "category": "HR", "status": "已解决", "priority": "low", "department_id": 2,
     "assigned_to": 7, "assigned_name": "赵专员",
     "agent_response": "考勤政策说明：1. 每月可迟到 3 次（每次 30 分钟内），超出扣减相应工资 2. 迟到超过 1 小时需提交说明 3. 连续迟到 5 次以上将约谈。特殊情况可申请调休。"},
    {"ticket_id": "TK-DEMO-022", "user_id": "admin", "user_name": "系统管理员",
     "content": "生产环境容器日志太多撑爆磁盘了，需要配置日志轮转策略",
     "category": "运维", "status": "已解决", "priority": "high", "department_id": 4,
     "assigned_to": 13, "assigned_name": "黄工",
     "agent_response": "已处理：1. 清理了 50GB 历史日志 2. 配置了 Docker 容器日志轮转（max-size=100m, max-file=3）3. 添加了磁盘使用率监控告警阈值 80%。"},
]

# ═══════════════════════════════════════════════════════════
# 工单处理模式
# ═══════════════════════════════════════════════════════════

PATTERNS = [
    {"pattern_id": "pat_it_001", "category": "IT", "problem_summary": "电脑蓝屏/系统崩溃",
     "solution": "记录错误码 -> 安全模式 -> 内存诊断 -> 检查驱动",
     "keywords": ["蓝屏", "崩溃", "死机", "错误码", "重启"], "confidence": 0.92, "frequency": 15},
    {"pattern_id": "pat_it_002", "category": "IT", "problem_summary": "VPN/网络连接故障",
     "solution": "检查本地网络 -> 重启 VPN 客户端 -> 检查配置",
     "keywords": ["VPN", "连不上", "网络", "超时", "断网"], "confidence": 0.88, "frequency": 12},
    {"pattern_id": "pat_it_003", "category": "IT", "problem_summary": "密码/账号重置",
     "solution": "SSO 门户自助重置 -> 验证身份 -> 设置新密码",
     "keywords": ["密码", "账号", "登录", "忘记", "重置"], "confidence": 0.95, "frequency": 20},
    {"pattern_id": "pat_hr_001", "category": "HR", "problem_summary": "请假申请",
     "solution": "确认假种 -> HR 系统提交 -> 经理审批",
     "keywords": ["请假", "年假", "事假", "病假", "休假"], "confidence": 0.90, "frequency": 25},
    {"pattern_id": "pat_fin_001", "category": "财务", "problem_summary": "差旅报销",
     "solution": "填写报销单 -> 附发票 -> 经理审批 -> 财务审核 -> 打款",
     "keywords": ["报销", "差旅", "发票", "费用", "出差"], "confidence": 0.85, "frequency": 18},
    {"pattern_id": "pat_ops_001", "category": "运维", "problem_summary": "服务器告警/502错误",
     "solution": "确认告警级别 -> 查看日志 -> 执行 SOP -> 恢复后发事故报告",
     "keywords": ["服务器", "502", "告警", "宕机", "无法访问"], "confidence": 0.82, "frequency": 8},
]

# ═══════════════════════════════════════════════════════════
# 用户反馈
# ═══════════════════════════════════════════════════════════

FEEDBACKS = [
    {"feedback_id": "fb_001", "ticket_id": "TK-DEMO-001", "user_id": "zhangsan",
     "rating": 5, "feedback_type": "positive", "comment": "处理很快，步骤很清晰，蓝屏问题已经解决了"},
    {"feedback_id": "fb_002", "ticket_id": "TK-DEMO-002", "user_id": "zhangsan",
     "rating": 4, "feedback_type": "positive", "comment": "VPN 已经恢复了，希望以后能更快响应"},
    {"feedback_id": "fb_003", "ticket_id": "TK-DEMO-005", "user_id": "lisi",
     "rating": 5, "feedback_type": "positive", "comment": "C 盘清理后电脑快多了，谢谢"},
    {"feedback_id": "fb_004", "ticket_id": "TK-DEMO-009", "user_id": "wangwu",
     "rating": 4, "feedback_type": "positive", "comment": "年假信息查得很清楚"},
    {"feedback_id": "fb_005", "ticket_id": "TK-DEMO-012", "user_id": "zhangsan",
     "rating": 3, "feedback_type": "neutral", "comment": "查到了进度，但是到账时间太长了"},
    {"feedback_id": "fb_006", "ticket_id": "TK-DEMO-014", "user_id": "admin",
     "rating": 5, "feedback_type": "positive", "comment": "紧急情况处理得不错，10 分钟就恢复了"},
    {"feedback_id": "fb_007", "ticket_id": "TK-DEMO-018", "user_id": "lisi",
     "rating": 4, "feedback_type": "positive", "comment": "企业微信通知已恢复"},
    {"feedback_id": "fb_008", "ticket_id": "TK-DEMO-019", "user_id": "wangwu",
     "rating": 5, "feedback_type": "positive", "comment": "打印机问题完美解决"},
]

# ═══════════════════════════════════════════════════════════
# 复盘记录
# ═══════════════════════════════════════════════════════════

REVIEWS = [
    {"review_id": "rv_001", "ticket_id": "TK-DEMO-001", "category": "IT",
     "classification_score": 0.95, "rag_hit_rate": 1.0, "response_quality": 0.90,
     "overall_score": 0.92, "suggestions": [], "follow_up_needed": False},
    {"review_id": "rv_002", "ticket_id": "TK-DEMO-002", "category": "IT",
     "classification_score": 0.90, "rag_hit_rate": 1.0, "response_quality": 0.85,
     "overall_score": 0.88, "suggestions": ["可以考虑增加 VPN 常见问题 FAQ"], "follow_up_needed": True},
    {"review_id": "rv_003", "ticket_id": "TK-DEMO-009", "category": "HR",
     "classification_score": 0.88, "rag_hit_rate": 1.0, "response_quality": 0.92,
     "overall_score": 0.90, "suggestions": [], "follow_up_needed": False},
    {"review_id": "rv_004", "ticket_id": "TK-DEMO-012", "category": "财务",
     "classification_score": 0.85, "rag_hit_rate": 0.5, "response_quality": 0.70,
     "overall_score": 0.72, "suggestions": ["报销进度查询建议提供更详细的节点信息", "考虑接入财务系统实现实时状态查询"], "follow_up_needed": True},
    {"review_id": "rv_005", "ticket_id": "TK-DEMO-014", "category": "运维",
     "classification_score": 0.95, "rag_hit_rate": 1.0, "response_quality": 0.95,
     "overall_score": 0.95, "suggestions": [], "follow_up_needed": False},
]

# ═══════════════════════════════════════════════════════════
# 知识缺口
# ═══════════════════════════════════════════════════════════

KNOWLEDGE_GAPS = [
    {"gap_id": "gap_001", "category": "IT", "source_tickets": ["TK-DEMO-006"],
     "suggested_title": "[IT] 笔记本电脑屏幕坏点检测与保修流程",
     "suggested_content": "屏幕坏点处理流程：1. 使用屏幕检测工具确认坏点位置和数量 2. 拍照留存凭证 3. 联系 IT 部门提交保修申请 4. 根据保修政策，3 个以上坏点可申请换屏 5. 预计维修时间 3-5 个工作日",
     "keywords": ["屏幕", "坏点", "笔记本", "保修", "亮点"], "frequency": 2, "resolved": False},
    {"gap_id": "gap_002", "category": "运维", "source_tickets": ["TK-DEMO-015"],
     "suggested_title": "[运维] MySQL 慢查询排查与优化指南",
     "suggested_content": "慢查询排查步骤：1. 开启慢查询日志 2. 使用 EXPLAIN 分析执行计划 3. 检查索引使用情况 4. 优化 SQL 语句 5. 考虑读写分离或分表方案",
     "keywords": ["MySQL", "慢查询", "数据库", "SQL", "索引"], "frequency": 1, "resolved": False},
]


# ═══════════════════════════════════════════════════════════
# 写入函数
# ═══════════════════════════════════════════════════════════

def seed_tickets():
    """写入演示工单到数据库"""
    from ticket_agent.database import session_scope
    from ticket_agent.database.models import TicketRecord

    with session_scope() as session:
        existing = session.query(TicketRecord).count()
        if existing > 0:
            import sqlalchemy
            session.execute(sqlalchemy.text("DELETE FROM ticket_records"))
            logger.info(f"  清空 {existing} 条旧工单")

        for t in SAMPLE_TICKETS:
            record = TicketRecord(**t)
            session.add(record)

    with session_scope() as session:
        count = session.query(TicketRecord).count()
    logger.info(f"  ✓ 写入 {count} 条演示工单")


def seed_patterns():
    """写入工单处理模式到 JSON"""
    path = os.path.join(DATA_DIR, "ticket_patterns.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(PATTERNS, f, ensure_ascii=False, indent=2)
    logger.info(f"  ✓ 写入 {len(PATTERNS)} 个工单模式")


def seed_feedback():
    """写入用户反馈到 JSON"""
    path = os.path.join(DATA_DIR, "ticket_feedback.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(FEEDBACKS, f, ensure_ascii=False, indent=2)
    logger.info(f"  ✓ 写入 {len(FEEDBACKS)} 条反馈")


def seed_reviews():
    """写入复盘记录到 JSON"""
    path = os.path.join(DATA_DIR, "ticket_reviews.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(REVIEWS, f, ensure_ascii=False, indent=2)
    logger.info(f"  ✓ 写入 {len(REVIEWS)} 条复盘记录")


def seed_knowledge_gaps():
    """写入知识缺口到 JSON"""
    path = os.path.join(DATA_DIR, "knowledge_gaps.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(KNOWLEDGE_GAPS, f, ensure_ascii=False, indent=2)
    logger.info(f"  ✓ 写入 {len(KNOWLEDGE_GAPS)} 个知识缺口")


def run():
    """执行所有演示数据生成"""
    logger.info("")
    logger.info("=" * 50)
    logger.info("  生成演示数据...")
    logger.info("=" * 50)
    seed_tickets()
    seed_patterns()
    seed_feedback()
    seed_reviews()
    seed_knowledge_gaps()
    logger.info("=" * 50)
    logger.info("  演示数据就绪！")
    logger.info("  登录账号: admin / 123456")
    logger.info("  访问地址: http://localhost:8000")
    logger.info("=" * 50)


if __name__ == "__main__":
    run()
