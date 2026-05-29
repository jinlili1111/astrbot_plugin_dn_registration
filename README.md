# 龙之谷 QQ 注册 AstrBot 插件

只提供龙之谷账号注册功能：账号固定使用发送者 QQ 号，密码必须是 6 位数字。

## 指令

- `/dn注册 123456`

默认只允许私聊使用，群聊中会提示用户私聊机器人，避免密码泄露。

## 数据库

插件通过 SQL Server 连接 `DNMembership` 账号库，调用注册存储过程 `__NX__CreateAccount`。数据库连接、账号库名、存储过程名都可在 AstrBot 插件配置中修改。

不要把真实数据库密码写入仓库。请在 AstrBot WebUI 的插件配置里填写。

## 配置项

- `database.server`：SQL Server 地址。
- `database.port`：SQL Server 端口。
- `database.user`：数据库用户名。
- `database.password`：数据库密码。
- `database.membership_database`：账号库名，默认 `DNMembership`。
- `register_procedure`：注册存储过程名，默认 `__NX__CreateAccount`。
- `private_chat_only`：默认开启，只允许私聊注册。
- `create_audit_table`：默认开启，创建插件注册审计表。

## 验证

本地可执行：

```bash
python -m py_compile main.py
```
