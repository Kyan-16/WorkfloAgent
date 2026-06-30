"""
种子数据：部门 + 用户 + 示例工单

创建模拟企业组织架构，每个部门有工程师和经理，方便演示流转。
"""
import datetime
import logging

from ticket_agent.database import session_scope
from ticket_agent.database.models import Department, User, TicketRecord

logger = logging.getLogger(__name__)


def seed_departments():
    """创建 4 个核心部门"""
    depts = {
        "IT": "网络/系统/硬件/软件技术支持",
        "HR": "人事/招聘/薪酬/员工关系",
        "财务": "报销/发票/预算/合同/差旅",
        "运维": "服务器/数据库/部署/监控告警",
    }
    with session_scope() as session:
        existing = {d.name for d in session.query(Department).all()}
        for name, desc in depts.items():
            if name not in existing:
                session.add(Department(name=name, description=desc))
                logger.info(f"  创建部门: {name}")
    logger.info(f"  部门就绪: {list(depts.keys())}")


def seed_users():
    """创建模拟用户，覆盖 4 种角色（默认密码: 123456）"""

    from passlib.hash import bcrypt
    _default_pw = bcrypt.hash("123456")

    users_data = [
        # ── 管理员 ──
        {"user_id": "admin", "name": "系统管理员", "role": "admin", "dept": None},

        # ── IT 部门（经理1 + 工程师3 + 员工3）──
        {"user_id": "it_li", "name": "李经理", "role": "manager", "dept": "IT"},
        {"user_id": "it_wang", "name": "王工", "role": "engineer", "dept": "IT"},
        {"user_id": "it_zhao", "name": "赵工", "role": "engineer", "dept": "IT"},
        {"user_id": "it_chen", "name": "陈工", "role": "engineer", "dept": "IT"},
        {"user_id": "zhangsan", "name": "张三", "role": "employee", "dept": "IT"},
        {"user_id": "zhaoliu", "name": "赵六", "role": "employee", "dept": "IT"},
        {"user_id": "sunqi", "name": "孙七", "role": "employee", "dept": "IT"},

        # ── HR 部门（经理1 + 工程师2 + 员工2）──
        {"user_id": "hr_wang", "name": "王经理", "role": "manager", "dept": "HR"},
        {"user_id": "hr_zhao", "name": "赵专员", "role": "engineer", "dept": "HR"},
        {"user_id": "hr_liu", "name": "刘专员", "role": "engineer", "dept": "HR"},
        {"user_id": "lisi", "name": "李四", "role": "employee", "dept": "HR"},
        {"user_id": "zhouba", "name": "周八", "role": "employee", "dept": "HR"},

        # ── 财务部门（经理1 + 工程师2 + 员工2）──
        {"user_id": "fin_zheng", "name": "郑经理", "role": "manager", "dept": "财务"},
        {"user_id": "fin_liu", "name": "刘专员", "role": "engineer", "dept": "财务"},
        {"user_id": "fin_wu", "name": "吴专员", "role": "engineer", "dept": "财务"},
        {"user_id": "wangwu", "name": "王五", "role": "employee", "dept": "财务"},
        {"user_id": "qianjiu", "name": "钱九", "role": "employee", "dept": "财务"},

        # ── 运维部门（经理1 + 工程师3 + 员工2）──
        {"user_id": "ops_zhang", "name": "张经理", "role": "manager", "dept": "运维"},
        {"user_id": "ops_li", "name": "李工", "role": "engineer", "dept": "运维"},
        {"user_id": "ops_huang", "name": "黄工", "role": "engineer", "dept": "运维"},
        {"user_id": "ops_zhou", "name": "周工", "role": "engineer", "dept": "运维"},
        {"user_id": "wushi", "name": "吴十", "role": "employee", "dept": "运维"},
        {"user_id": "zheng_shi", "name": "郑十一", "role": "employee", "dept": "运维"},
    ]

    with session_scope() as session:
        existing_ids = {u.user_id for u in session.query(User).all()}
        dept_map = {d.name: d for d in session.query(Department).all()}

        for u in users_data:
            if u["user_id"] in existing_ids:
                continue
            user = User(
                user_id=u["user_id"],
                name=u["name"],
                role=u["role"],
                department_id=dept_map[u["dept"]].id if u["dept"] else None,
                email=f"{u['user_id']}@company.com",
                hashed_password=_default_pw,
            )
            session.add(user)

    with session_scope() as session:
        total = session.query(User).count()
        roles = {}
        for u in session.query(User).all():
            roles[u.role] = roles.get(u.role, 0) + 1
        logger.info(f"  用户就绪: 共 {total} 人, 角色分布 {roles}")


def seed_sample_tickets():
    """创建示例工单（用于演示部门队列）"""
    with session_scope() as session:
        existing = session.query(TicketRecord).count()
        if existing > 0:
            logger.info(f"  已有 {existing} 条工单记录，跳过示例")
            return

    samples = [
        {"ticket_id": "TK-DEMO-001", "user_id": "zhangsan", "user_name": "张三",
         "content": "电脑蓝屏了，错误码 0x0000001A", "category": "IT",
         "status": "处理中", "priority": "normal", "department_id": 1,
         "assigned_to": 3, "assigned_name": "赵工"},
        {"ticket_id": "TK-DEMO-002", "user_id": "lisi", "user_name": "李四",
         "content": "请三天年假，下周一至周三", "category": "HR",
         "status": "待审批", "priority": "normal", "department_id": 2,
         "needs_approval": True, "approval_status": "pending"},
        {"ticket_id": "TK-DEMO-003", "user_id": "wangwu", "user_name": "王五",
         "content": "报销上海出差高铁票和住宿费，共 2800 元", "category": "财务",
         "status": "待审批", "priority": "normal", "department_id": 3,
         "needs_approval": True, "approval_status": "pending"},
        {"ticket_id": "TK-DEMO-004", "user_id": "admin", "user_name": "系统管理员",
         "content": "服务器 502 错误，线上用户无法登录！", "category": "运维",
         "status": "处理中", "priority": "urgent", "department_id": 4,
         "assigned_to": 12, "assigned_name": "李工"},
        {"ticket_id": "TK-DEMO-005", "user_id": "zhangsan", "user_name": "张三",
         "content": "申请开通数据库只读账号给数据组", "category": "IT",
         "status": "待处理", "priority": "low", "department_id": 1},
    ]

    with session_scope() as session:
        for s in samples:
            session.add(TicketRecord(**s))
    logger.info(f"  添加 {len(samples)} 条示例工单")


def run_all():
    """执行所有种子数据初始化"""
    logger.info("开始初始化种子数据...")
    seed_departments()
    seed_users()
    seed_sample_tickets()

    # 生成丰富的演示数据
    try:
        from ticket_agent.database.seed_demo import run as seed_demo_data
        seed_demo_data()
    except Exception as e:
        logger.warning(f"演示数据生成失败（不影响基础功能）: {e}")

    logger.info("种子数据初始化完成")
