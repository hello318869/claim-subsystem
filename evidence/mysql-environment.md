# 本项目隔离 MySQL 环境与连接验证

验证日期：2026-11-05。执行主体：Codex 代理。本文记录实际本机环境操作，不代表学生本人独立完成，也不代表应用业务测试已通过。

## 实例边界

| 项目 | 实际值 |
| --- | --- |
| 数据库引擎 | MySQL Community Server 8.0.46-0ubuntu0.24.04.4 |
| 服务器二进制 | WSL Ubuntu `/usr/sbin/mysqld` |
| 执行用户 | WSL 普通用户 `asusjian` |
| 监听 | 仅 `127.0.0.1:33307` |
| 唯一实例目录 | `/tmp/se-claim-20261105-44cc3b4f` |
| 数据目录 | `/tmp/se-claim-20261105-44cc3b4f/data` |
| Unix socket | `/tmp/se-claim-20261105-44cc3b4f/mysql.sock` |
| 开发库 | `claim_dev`，utf8mb4 |
| 测试库 | `claim_test`，utf8mb4 |
| 应用用户 | `claim_app`，权限仅授予以上两个库 |
| 完成验证时进程 | PID `1640`；PID 会随重启改变，应通过脚本动态核验 |

已有 WSL MySQL 保持监听 `127.0.0.1:3306`，核查前后进程均为 PID `480`。本次没有启动、停止或重配该服务，没有连接已有业务数据库，也没有修改 Windows MySQL84 服务。

## 凭据与环境文件

应用密码由密码学随机数生成器产生，保存在项目 `.env` 与 `.env.test`，未写入此记录或工具输出。两个文件均有随机 `AUTH_SECRET` 与 `DEMO_MODE=true`。

- `.env` 的 `DATABASE_URL` 指向 `claim_dev`，`TEST_DATABASE_URL` 指向 `claim_test`。
- `.env.test` 的 `DATABASE_URL` 与 `TEST_DATABASE_URL` 均指向 `claim_test`。
- URL 形式为 `mysql+pymysql://claim_app:<本机随机密码>@127.0.0.1:33307/claim_dev?charset=utf8mb4`，测试库替换末尾库名。
- 独立实例 root 密码另存于唯一实例目录的 `admin-password`，Unix 权限为 `0600`，由脚本内部使用。
- 环境文件应作为本机配置保留，提交包与版本库中应排除真实凭据。

## 可复现操作

在 Windows PowerShell 中运行：

```powershell
& 'D:\软工大作业\claim-subsystem\scripts\local_mysql.ps1' -Action Start
& 'D:\软工大作业\claim-subsystem\scripts\local_mysql.ps1' -Action Status
& 'D:\软工大作业\claim-subsystem\scripts\local_mysql.ps1' -Action Stop
```

首次 `Start` 创建此任务专用环境文件、初始化独立 datadir、启动实例并创建两个数据库与受限账号；之后 `Start` 复用同一 datadir 和本机随机凭据。不会覆盖格式不匹配的已有 `.env` 或内容不同的 `.env.test`。不需要 Docker、现有 MySQL 的密码或 sudo 密码。

`Stop` 在执行 `SHUTDOWN` 或 `SIGTERM` 前核验：唯一实例目录及真实路径、目录属主、PID 格式、进程可执行文件、进程属主、命令行中的完整 datadir 和 socket。发现不匹配即拒绝操作。不会按进程名批量停止，不使用强制杀进程，不删除数据。停止后可再执行 `Start`。

当前 Codex 文件系统沙箱不能直接访问 WSL，且沙箱内 loopback 连接会超时；本次 WSL 和真实数据库连接核查使用正常的 `require_escalated` 自动审批执行，均获准完成。普通本机 PowerShell 不受此 Codex 沙箱限制。

该独立实例位于 `/tmp`，不作为长期部署。重启 WSL 后需要再次 `Start`；若系统清理 `/tmp`，脚本会重新初始化一个空的课程测试实例，不应在此存储唯一业务数据。

## 实际执行结果

1. 首次初始化与启动成功：MySQL 返回版本 `8.0.46-0ubuntu0.24.04.4`，PID `1503`，33307 端口。
2. Windows Python 3.11 中通过 PyMySQL 实际连接开发库和测试库，查询 `VERSION()`、`DATABASE()`、`CURRENT_USER()`、`@@port`、`@@transaction_isolation`。
3. 启停验证中发现，立即重启的预检查把 TCP `TIME_WAIT` 当作端口占用。脚本已修复：端口探测使用 `SO_REUSEADDR`，停止过程等待已核验进程退出。
4. 修复后完整 `Stop → Start → Status` 回归通过，最终 PID `1640`，实例保持运行。
5. 重启后通过 SQLAlchemy 与 PyMySQL 再次实际连接两库，结果如下。

| 环境文件 | 数据库 | VERSION | CURRENT_USER | @@port | 隔离级别 |
| --- | --- | --- | --- | --- | --- |
| `.env` | `claim_dev` | `8.0.46-0ubuntu0.24.04.4` | `claim_app@127.0.0.1` | `33307` | `REPEATABLE-READ` |
| `.env.test` | `claim_test` | `8.0.46-0ubuntu0.24.04.4` | `claim_app@127.0.0.1` | `33307` | `REPEATABLE-READ` |

两次连接均尝试 `SELECT COUNT(*) FROM mysql.user`，均被拒绝，MySQL 错误码为 `1142`，证明应用账号未取得该系统表读取权限。

最终监听核查输出：

```text
LISTEN 127.0.0.1:3306    原有 MySQL，PID 480，保持运行
LISTEN 127.0.0.1:33307   本项目独立 MySQL，PID 1640
```

以上是数据库引擎、连接、账号范围及实例生命周期验证。应用事务、并发认领、接口权限和业务回归必须由项目测试另行执行并记录，本文不声称这些测试已完成。
