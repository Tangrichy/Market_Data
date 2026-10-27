# Release 阻塞问题修复说明（客户端规避方案）

对应问题报告：[../Issue.md](../Issue.md)。原目录 `pybind_gtja/` 保持原样未改动，
本目录是独立副本，所有修改只在这里。

> **注意（分支现状）**：本目录的修改建立在"原目录未动"的前提上开发与验证。本分支
> 另有提交 `3041bac` 直接修改了 `pybind_gtja/`（SIGURG 方案），是针对同一问题的
> 另一套独立方案，与本目录互不依赖。两者对照见文末[两种方案对照](#两种方案对照)。

## 根因（两层）

1. **SDK 缺陷（官方侧，本方案只是绕过）**：
   `GtjaMdUserApi::Release()` 内部先写停止标志再 `pthread_join` 等待接收线程，
   而接收线程阻塞在无超时的 `pselect6` 上（V3.7.0.2 起接收由非阻塞改为 select）。
   停止标志无法唤醒正在等待的 select，只有新的网络报文能让接收线程醒来检查标志。
   连接静默（退订后、休市、无行情）时 Release 永远不会返回。
   公开 API 无 Stop/Disconnect 接口，SetConfig 也没有等待超时配置；
   官方 demo（recvTest.cpp）退出时干脆不调 Release()。

2. **包装层缺陷（客户端侧，本方案修复）**：
   原 `gtja_udp_api.cpp` 的 `Release()` 绑定不释放 GIL。若只做唤醒规避，
   唤醒报文的应答要回调 Python（需要 GIL），而 GIL 被阻塞的 Release 占住，
   会形成 "Release 持 GIL 等接收线程，接收线程等 GIL 回调" 的死锁。

## 修改清单

| 文件 | 修改 |
|---|---|
| `gtja_udp_api.cpp` | `release()`/`Join()` 进入 SDK 前 `py::gil_scoped_release` 释放 GIL；`release()` 先置空 `api_` 再调用 SDK，消除并发 UAF 窗口 |
| `pull_data.py` | 关闭顺序重排：退订 → **退出唤醒请求** → 有界等待 Release → 文件收尾；新增 `--release-timeout`（默认 10 秒）兜底强制退出；连接/登录阶段的异常退出也纳入同一关闭路径 |
| `vnpy_gtja_md/gtja_md_gateway.py` | `close()` 采用同一模式；SPI 保留到 Release 返回后才释放（在途回调仍引用它）；网关在宿主进程中不能强杀，超时只告警 |

### 退出唤醒的原理

在调用 `Release()` **之前**同步发送一个订阅请求。其应答报文必然在停止标志写入
之后到达（网络往返 >> 标志写入的指令耗时），从而唤醒接收线程：处理应答 →
循环回到停止标志检查 → 退出 → `Join` 返回 → `Release` 返回。
该请求与 `Release` 不并发调用 SDK，不依赖未公开的生命周期约定。

## 测试证据（2026-10-27，本机直连）

| 场景 | 原代码（pybind_gtja/） | 本目录修复后 |
|---|---|---|
| SSE `183.193.54.200:21002`，收数后 `--duration 2` 停止 | 复现卡死：before_Release 后无 after_Release，25 秒超时被杀（退出码 124） | 正常返回，退出码 0；唤醒应答出现在 before/after_Release 之间 |
| SZSE `183.63.193.58:42116`，收盘后静默连接停止 | — | 退出码 0 |
| 默认前置 `114.94.154.60:21002`，0 tick 静默 + Ctrl+C 人工停止 | — | 进程自行退出，退出码 0（`--preserve-status` 核实） |

基线复现与修复复测使用同一 SDK 库（`udpapi/Linux64/gcc9.3.1/libGtjaMdUserApi.so`，
SHA256 见 Issue.md）与同一前置、标的、参数，唯一变量是本目录的修改。

## 边界与遗留

- **兜底超时不是干净的 SDK 停止**：`--release-timeout` 到期后 `os._exit(3)` 强制
  退出，只能保证进程有界结束，不能证明 SDK 完成在途回调收尾。正常路径必须
  观察到 `after_Release`（即 Release 实际返回）。
- **组播/广播模式未覆盖**：不支持订阅的前置无法用订阅请求生成唤醒流量，
  只能依赖兜底超时；盘中组播流量持续时 Release 可自行返回。尚未实测。
- **连续创建/释放循环**（Issue.md 验收表最后一项）未在单进程内实测。
- **cpython-39 扩展未重编**：本环境用 rqsdk（Python 3.12）构建并验证。
  如需 py39，在对应解释器下执行 `python setup.py build_ext --inplace`。
- **根因仍在官方 SDK 二进制**：本方案是客户端规避，Issue.md 对 GTJA 的
  官方修复/调用约定诉求不变。修复包应使停止标志能唤醒接收等待，
  或提供官方停止接口/有限期的 select 等待。

## 复测方法

```bash
source /opt/conda/etc/profile.d/conda.sh && conda activate rqsdk   # 或任意 py3.12
cd pybind_gtja_fix
python setup.py build_ext --inplace
python -u pull_data.py --front tcp://183.193.54.200:21002 \
    --symbols 600000,688027 --exchange sse --duration 2 --cpu 1 --no-efvi
# 期望：出现 before_Release → （唤醒应答）→ after_Release，进程退出码 0
```

## 两种方案对照

本分支同时包含两套针对 Release 卡死的独立方案，目录互不重叠，可单独取用：

| | 本目录：唤醒报文方案 | `pybind_gtja/`：SIGURG 方案（提交 `3041bac`） |
|---|---|---|
| 原理 | Release 前同步发一个订阅请求，应答报文唤醒阻塞的接收线程，走正常停止流程 | `ReleaseWithTimeout(ms)` 在工作线程执行 Release，超时后以 SIGURG 打断 `pselect6`（EINTR）促其返回 |
| 改动位置 | 全部在本目录（独立副本） | 直接改原目录 `gtja_udp_api.cpp`、`pull_data.py`，新增 `repro_release_hang.py` |
| 调用入口 | `pull_data.py` / `gtja_md_gateway.py` 的关闭顺序重排 | 新绑定 `ReleaseWithTimeout`、`take_api`、`LastReleaseAbandoned` |
| 超时兜底 | `--release-timeout` 到期 `os._exit(3)`，进程有界结束 | 调用方不阻塞，超时放弃实例并置 `LastReleaseAbandoned` |
| 已知边界 | 组播/广播前置无订阅可发，只能靠兜底超时 | 信号打断路径未在本目录测试中验证，细节以其提交说明为准 |
| 验证记录 | 见上文"测试证据" | 见 `3041bac` 提交说明与 `repro_release_hang.py` |

选型：要求原目录不动、或以 SDK 正常停止路径收尾 → 本目录方案；
要求调用方绝不阻塞、或需要离线复现脚本 → `3041bac` 方案。
