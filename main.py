import asyncio
import re
from contextlib import contextmanager
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


class DNRegistrationPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}

    async def initialize(self):
        if self._get_bool("create_audit_table", True):
            try:
                await asyncio.to_thread(self._ensure_audit_table)
            except Exception as exc:
                logger.warning(
                    "DNRegistrationPlugin audit table init skipped. "
                    f"Please check database config: {exc}"
                )
        logger.info("DNRegistrationPlugin initialized")

    @filter.command("dn注册")
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def register_account(self, event: AiocqhttpMessageEvent, password: str = ""):
        """私聊注册龙之谷账号，账号固定使用QQ号，密码必须为6位数字。"""
        qq = str(event.get_sender_id() or "").strip()
        group_id = event.get_group_id()
        password = (password or "").strip()

        if self._get_bool("private_chat_only", True) and group_id:
            yield event.plain_result("密码属于隐私，请私聊机器人发送：/dn注册 123456")
            return
        if not qq or not qq.isdigit():
            yield event.plain_result("无法识别你的QQ号，注册失败。")
            return
        if len(qq) > 18:
            yield event.plain_result("QQ号长度超过注册系统限制，注册失败。")
            return
        if not password:
            yield event.plain_result("用法：/dn注册 123456")
            return
        if not re.fullmatch(r"\d{6}", password):
            yield event.plain_result("密码必须是6位数字。")
            return

        result = await asyncio.to_thread(self._register_account, qq, password)
        await asyncio.to_thread(
            self._record_audit,
            qq,
            "register",
            bool(result.get("success")),
            result.get("message", ""),
        )
        if result.get("success"):
            message = f"注册成功。\n账号：{qq}"
            if self._get_bool("show_success_password_hint", True):
                message += "\n请妥善保存你刚才设置的6位数字密码。"
            yield event.plain_result(message)
            return
        yield event.plain_result(result.get("message") or "注册失败，请稍后重试。")

    @contextmanager
    def _connection(self):
        try:
            import pymssql
        except ImportError as exc:
            raise RuntimeError(
                "pymssql is not installed. Install requirements.txt in the AstrBot "
                "container before using direct SQL Server registration."
            ) from exc

        db = self._get_dict("database")
        conn = pymssql.connect(
            server=str(db.get("server") or "127.0.0.1"),
            port=int(db.get("port") or 1433),
            user=str(db.get("user") or "sa"),
            password=str(db.get("password") or ""),
            database=str(db.get("membership_database") or "DNMembership"),
            charset=str(db.get("charset") or "utf8"),
            login_timeout=int(db.get("login_timeout") or 10),
            timeout=int(db.get("request_timeout") or 20),
            autocommit=False,
        )
        try:
            yield conn
        finally:
            conn.close()

    def _register_account(self, account_name: str, password: str) -> dict[str, Any]:
        try:
            with self._connection() as conn:
                with conn.cursor(as_dict=True) as cursor:
                    cursor.execute(
                        "SELECT TOP 1 AccountID FROM dbo.Accounts WHERE AccountName = %s",
                        (account_name,),
                    )
                    if cursor.fetchone():
                        return {"success": False, "message": "当前QQ号已注册。"}

                    procedure = self._procedure_name()
                    cursor.execute(
                        f"""
                        DECLARE @ret INT;
                        EXEC @ret = dbo.[{procedure}]
                            @AccountName = %s,
                            @NxLoginPwd = %s,
                            @params3 = %s;
                        SELECT @ret AS result_code;
                        """,
                        (account_name, password, None),
                    )
                    row = cursor.fetchone() or {}
                    conn.commit()

            result_code = self._coerce_int(row.get("result_code"), default=0)
            if result_code == 0:
                return {"success": True, "message": "注册成功。"}
            messages = {
                1: "当前QQ号已注册。",
                2: "账号或密码长度不符合注册系统限制。",
                3: "注册失败，请稍后重试。",
            }
            return {
                "success": False,
                "message": messages.get(result_code, f"注册失败，错误码：{result_code}。"),
            }
        except Exception as exc:
            logger.exception(f"DN account registration failed account={account_name}: {exc}")
            return {"success": False, "message": "注册失败，请联系管理员检查数据库配置。"}

    def _ensure_audit_table(self):
        table = self._audit_table_name()
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    IF OBJECT_ID(N'dbo.[{table}]', N'U') IS NULL
                    BEGIN
                        CREATE TABLE dbo.[{table}] (
                            id INT IDENTITY(1,1) PRIMARY KEY,
                            qq VARCHAR(32) NOT NULL,
                            account_name VARCHAR(50) NOT NULL,
                            action VARCHAR(32) NOT NULL,
                            success BIT NOT NULL,
                            message NVARCHAR(200) NULL,
                            created_at DATETIME NOT NULL DEFAULT GETDATE()
                        )
                    END
                    """
                )
                conn.commit()

    def _record_audit(self, qq: str, action: str, success: bool, message: str):
        if not self._get_bool("create_audit_table", True):
            return
        try:
            table = self._audit_table_name()
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO dbo.[{table}]
                            (qq, account_name, action, success, message)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (qq, qq, action, 1 if success else 0, message[:200]),
                    )
                    conn.commit()
        except Exception as exc:
            logger.warning(f"DN registration audit skipped qq={qq}: {exc}")

    def _procedure_name(self) -> str:
        name = str(self._get("register_procedure", "__NX__CreateAccount") or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
            raise ValueError("register_procedure must be a simple SQL identifier")
        return name

    def _audit_table_name(self) -> str:
        name = str(self._get("audit_table", "astrbot_dn_registration_audit") or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
            raise ValueError("audit_table must be a simple SQL identifier")
        return name

    def _get_dict(self, key: str) -> dict[str, Any]:
        value = self._get(key, {})
        return value if isinstance(value, dict) else {}

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self._get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _get(self, key: str, default: Any = None) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except Exception:
                return default

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
