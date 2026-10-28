# 国泰君安 UDP 行情 API Python 绑定

基于 pybind11 对官方 C++ API（V3.7.x）做的 Python 封装，用于在 Python 3.9 环境下快速拉取行情 tick 数据。

> 支持上交所（SSE）、深交所（SZSE）的股票与 ETF，以及沪深期权（8 位代码：`10011425`、`90007411`）；不支持期货合约。

## 文件说明

| 文件 | 说明 |
|------|------|
| `gtja_udp_api.cpp` | pybind11 C++ 绑定源码 |
| `setup.py` | 编译脚本 |
| `pull_data.py` | Python 拉取数据示例 |
| `verify_release.py` | `Release()` 退出行为复验（offline/silent/cycles/concurrent 免账号，live 需前置与账号） |

## 环境要求

- Python 3.9+（本机使用 conda 环境 `py39`；**扩展的 ABI 与版本绑定，用哪个版本运行就用哪个版本编译**）
- pybind11（Python 3.12 需 `>=2.11.1`；pybind11 3.x 需编译器支持 C++17）
- g++（当前系统为 11.4.0，与 gcc9.3.1 编译的官方库可兼容）
- **国泰君安 udpapi SDK**：位于仓库根目录的 [`../udpapi_new`](../udpapi_new)，提供 `include/` 头文件和 `Linux64/gcc9.3.1/libGtjaMdUserApi.so`；没有 SDK 无法编译或运行
- **SDK 版本：V3.7.1.1（build 20250624）**。相对旧的 V3.7.0.6，本分支依赖的三处差异：
  1. `GtjaMdUserSpi::OnRtnDepthSnapshot` 新增 `const SecurityExtraInfo*` 参数（**ABI 不兼容**，旧绑定无法直接加载新库）；
  2. 新增 `SecurityExtraInfo{DynRefPrice, VirMatch, IOPV}` 与 `GtjaMdHeaderFieldV3::SecurityExtraInfoIdx`；
  3. `Release()` 会主动唤醒停在 `select` 的接收线程，不再依赖下一条报文（旧版正是因此卡死，见 Issue.md）。

## 编译

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate py39
cd /root/private_data/Market_Data/pybind_gtja
python setup.py build_ext --inplace
```

编译成功后会在当前目录生成 `gtja_udp_api.cpython-3XX-x86_64-linux-gnu.so`，其中 `3XX` 是编译用的 Python 版本。

> **新环境 / 换了目录后要重新编译。** 仓库里提交的 `.so` 把旧的绝对路径（`/root/private_data/trading/udpapi/...`）写进了 rpath，跨机器会找不到动态库。建议先 `rm -rf build` 再编译，避免复用旧目标文件；编译后用 `readelf -d gtja_udp_api*.so | grep -Ei 'rpath|runpath'` 确认指向本仓库的 `udpapi_new/Linux64/gcc9.3.1`（不同环境下可能是 `RUNPATH` 或 `RPATH`，两者都能生效）。

### 在 Python 3.10 / 3.11 / 3.12 上使用

官方 `libGtjaMdUserApi.so` 是纯 C++ 库，与 Python 版本无关，**只需为当前解释器重编绑定模块**。

本机 `rqsdk` 环境（Python 3.10.20）已验证可用：

```bash
/opt/conda/envs/rqsdk/bin/pip install pybind11          # 该环境原本未安装
cd /root/private_data/Market_Data/pybind_gtja
rm -rf build
/opt/conda/envs/rqsdk/bin/python setup.py build_ext --inplace
/opt/conda/envs/rqsdk/bin/python -c "import gtja_udp_api; print('OK')"
```

实测（2026-10-28，SSE 21002）：连接登录、订阅、收数、CSV 落盘正常，`api.Release()` 在 proxychains 下 3–70 ms 返回，进程自行退出、退出码 0。2026-10-21 在旧 V3.7.0.6 上曾出现 `Release()` 不返回，该问题已随 V3.7.1.1 消失（见根目录 README「验证 Release」）。

其他版本以 3.12 为例：

```bash
python3.12 -m venv ~/gtja-venv
source ~/gtja-venv/bin/activate

# Python 3.12 的 venv 不再自带 setuptools，必须显式安装
pip install setuptools 'pybind11>=2.11.1'

cd pybind_gtja
rm -rf build
python setup.py build_ext --inplace

python -c "import gtja_udp_api; print('OK')"   # 打印 OK 即成功
```

生成的 `.so` 带 `cpython-312` 标签，与仓库预置的 `cpython-39` 版本可以共存。之后**固定用同一个 3.12 解释器运行**；若又切回 py39，需使用 py39 编出的 `.so`（两者互不通用）。

常见报错：

| 报错 | 处理 |
|------|------|
| `No module named 'setuptools'` | `pip install setuptools` |
| `Python.h: No such file` | 安装 `python3.12-dev`，或改用 conda 环境 |
| `pybind11 requires C++17 or later` | 升级 g++ 到 7+，或安装 `pybind11<3` |

## 运行示例

### 本机运行（需 proxychains）

本机无法直连公网行情前置，且预置的扩展模块是 `cpython-39`，必须用 py39 解释器经 proxychains 启动（若已为 3.12 重编，则换成对应的 3.12 解释器）：

```bash
cd /root/private_data/Market_Data/pybind_gtja
proxychains4 -q -f /etc/proxychains4.conf \
  /opt/conda/envs/py39/bin/python -u pull_data.py \
  --front tcp://183.193.54.200:21002 \
  --user 00000001 --password 88888888 \
  --symbols 600000,688027 --exchange sse \
  --output sse_ticks.csv --duration 60
```

> `-u` 用于关闭 stdout 缓冲。`api.Release()` 在 V3.7.1.1 上可正常返回（proxychains 下实测 3–70 ms），外层 `timeout` 只作兜底，不再是被杀掉的常态。

### 上交所 / 深交所

> 以下命令中的 `python` 指**编译该扩展时所用的解释器**（本机为 py39）。若用系统默认的 Python 3.11 而扩展是 cpython-39，会报 `ModuleNotFoundError: No module named 'gtja_udp_api'`；3.12 同理，需按上文重编。

```bash
# 上交所：21002 前置
python pull_data.py \
    --front tcp://183.193.54.200:21002 \
    --user 00000001 \
    --password 88888888 \
    --symbols 600000,688027 \
    --exchange sse \
    --output sse_ticks.csv \
    --duration 60

# 深交所：42116 前置
python pull_data.py \
    --front tcp://183.63.193.58:42116 \
    --user 00000001 \
    --password 88888888 \
    --symbols 000001,300750 \
    --exchange szse \
    --output szse_ticks.csv \
    --duration 60
```

### 环境变量

```bash
export GTJA_FRONT=tcp://183.193.54.200:21002
export GTJA_USER=00000001
export GTJA_PASSWORD=88888888
export GTJA_SYMBOLS=600000,688027
export GTJA_EXCHANGE=sse
python pull_data.py
```

## 参数说明

- `--front`: 行情前置地址（SSE 用 21002，SZSE 用 42116）
- `--user`: 资金账号
- `--password`: 密码
- `--symbols`: 合约代码，逗号分隔。股票/ETF 为 6 位数字（如 `600000,688027`），期权为 8 位数字（上交所 `10011425`、深交所 `90007411`）
- `--exchange`: 交易所，仅可选 `sse` / `szse`，留空由前置判断
- `--cpu`: 绑定接收线程 CPU 核，默认 `1`
- `--no-efvi`: 关闭 efvi 加速
- `--output`: 输出 csv 文件路径
- `--duration`: 运行时长（秒），默认 `0` 表示一直运行
- `--levels`: CSV 保存的盘口档位数，默认 `5`
- `--multi`: 打印全部档位（默认只打印第 1 档）

## 支持范围

- 支持上交所（`sse`）、深交所（`szse`）的 6 位股票/ETF 代码，以及 8 位期权代码：上交所期权以 `1` 开头，深交所期权以 `9` 开头；
- 期货合约（如 `ag2612`）、其他位数或非数字代码会被直接拒绝；
- `21002` 端口前置只推送 SSE 行情，`42116` 端口前置只推送 SZSE 行情，不能混用（期权按所属交易所选前置，并带 `--exchange sse` / `--exchange szse`）；
- 订阅成功后服务端会先快速回放当日历史 tick，再转入实时推送；期权快照按固定间隔推送，上交所约 30 秒一档，深交所为数秒一档（实测 3–6 秒，故同样时长内条数远多于沪市）。

### 期权拉取示例

```bash
# 上交所：50ETF 期权
proxychains4 -q -f /etc/proxychains4.conf /opt/conda/envs/py39/bin/python -u pull_data.py \
  --front tcp://183.193.54.200:21002 \
  --user 83607651 --password 88888888 \
  --symbols 10011425 --exchange sse \
  --output opt_10011425.csv --duration 60

# 深交所：创业板ETF 期权（注意是 8 位，9007411 会收不到任何数据）
proxychains4 -q -f /etc/proxychains4.conf /opt/conda/envs/py39/bin/python -u pull_data.py \
  --front tcp://183.63.193.58:42116 \
  --user 83607651 --password 88888888 \
  --symbols 90007411 --exchange szse \
  --output opt_90007411.csv --duration 60
```

2026-10-28 实测：上交所 `10011425`（50ETF 期权）8 秒 17 条、深交所 `90007411`（创业板ETF 期权）8 秒 204 条，订阅返回 0，`last_price` / 五档盘口 / `open_interest`（持仓量）均有值，CSV 正常落盘。注意 `dyn_ref_price` / `vir_match` / `iopv` 三列在所有已测合约（股票、ETF、沪深期权）上均为空，原因见根目录 README 的 SecurityExtraInfo 一节。

## 注意事项

1. SDK 保持在仓库根目录的 `../udpapi_new` 即可，**不需要复制到本目录**。`setup.py` 通过 `UDPAPI_ROOT` 定位 SDK 根目录，并设置 `rpath`：
   ```python
   UDPAPI_ROOT = os.getenv("GTJA_UDPAPI_ROOT") or os.path.join(os.path.dirname(ROOT), "udpapi_new")
   ```
   编译脚本会在 `Linux64/` 下自动挑选存在的 gcc 版本目录（优先 `gcc9.3.1`），SDK 放在别处时可用 `GTJA_UDPAPI_ROOT` / `GTJA_UDPAPI_LIB_DIR` 覆盖。

`GtjaMdUserApi` 在 Python 中直接实例化：

```python
import gtja_udp_api
api = gtja_udp_api.GtjaMdUserApi("api.log")
```

释放时调用 `api.Release()`，或让对象自然析构即可。`Release()` 幂等且线程安全（并发调用时只有一个真正释放，其余等待后直接返回）；释放后再调用其它接口会抛 `RuntimeError: API already released`。`RegisterSpi` 传入的 SPI 会随 API 对象一起保持存活，不需要自己在 Python 侧另存引用。

> 不要在 SPI 回调里调用 `Release()`：回调运行在 SDK 的收包线程上，而 `Release()` 要等这个线程退出，两边会互相等待。请在主线程或独立的清理线程里释放。
2. 运行时应能通过 `rpath` 自动找到动态库；如仍报找不到库，可手动设置：
   ```bash
   export LD_LIBRARY_PATH=/root/private_data/Market_Data/udpapi_new/Linux64/gcc9.3.1:$LD_LIBRARY_PATH
   ```
3. 订阅功能仅在 TCP 单播模式下有效，组播/广播模式会自动推送全量行情。
4. `GtjaMdInstrumentFieldV3.InstrumentID` 在 C 头文件中是柔性数组，Python 侧通过只读属性获取完整字符串。
