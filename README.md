# Market_Data

期货与证券实时行情接入工具集，提供两个可直接运行的行情脚本：

- [ctp_mdapi.py](ctp_mdapi.py) — 基于 CTP 的期货行情
- [pybind_gtja/pull_data.py](pybind_gtja/pull_data.py) — 基于国泰君安 UDP 行情的沪深股票行情（仅 SSE/SZSE）

## 环境要求

- `ctp_mdapi.py`：任意 Python 3.7+，`pip install vnpy_ctp` 即可。
- `pull_data.py`：**`gtja_udp_api` 扩展必须按你实际使用的 Python 版本现场编译**（ABI 与版本强绑定）。仓库里预置的 `.so` 是 `cpython-39`，因此：
  - 用 3.9 跑 → 可直接使用预置扩展；
  - 用 3.10 / 3.11 / **3.12** 跑 → 先重新编译，否则报 `ModuleNotFoundError: No module named 'gtja_udp_api'`（Python 会直接忽略 ABI 不匹配的 `.so`）。
- `pip install pybind11`、g++（需支持 C++17）、`libGtjaMdUserApi.so`
- Linux x86_64，CTP 需要中文 locale（GBK/GB18030）
- **使用国泰君安 UDP 行情前，必须先准备 `udpapi/` SDK**（C++ 头文件 + 动态库），见下文「行情 SDK 依赖」

> 本机默认的 `python` 是 conda base 的 3.11，`pull_data.py` 需显式指定一个**已为其编译过扩展**的解释器（py39，或下文的 rqsdk/3.10）。

### 选择 Python 解释器

#### 本机（已有 py39 环境）

```bash
# 方式一：激活 py39 环境（之后 python 即为 3.9）
source /opt/conda/etc/profile.d/conda.sh
conda activate py39

# 方式二：直接用 py39 的绝对路径（无需激活，适合脚本/定时任务）
/opt/conda/envs/py39/bin/python pull_data.py ...
```

确认解释器版本：

```bash
python -c "import sys; print(sys.version)"   # 应输出 3.9.x
```

#### conda rqsdk 环境（Python 3.10，已实测）

`rqsdk` 是 Python 3.10.20，与预置的 `cpython-39` 扩展不兼容，需要先为它单独编译一次（只需一次）：

```bash
/opt/conda/envs/rqsdk/bin/pip install pybind11          # 该环境原本未安装
cd /root/private_data/Market_Data/pybind_gtja
rm -rf build
/opt/conda/envs/rqsdk/bin/python setup.py build_ext --inplace

/opt/conda/envs/rqsdk/bin/python -c "import gtja_udp_api; print('OK')"
```

编译产物 `gtja_udp_api.cpython-310-x86_64-linux-gnu.so` 与预置的 `cpython-39` 版本共存，互不影响。之后这样运行（本机仍需 proxychains）：

```bash
cd /root/private_data/Market_Data/pybind_gtja
timeout 100 proxychains4 -q -f /etc/proxychains4.conf \
  /opt/conda/envs/rqsdk/bin/python -u pull_data.py \
  --front tcp://183.193.54.200:21002 \
  --user 00000001 --password 88888888 \
  --symbols 600000,688027 --exchange sse \
  --output sse_ticks.csv --duration 20
```

> **实测（2026-10-21，SSE 21002）**：登录、订阅、历史快照回放与实时 tick 均正常，20 秒收到 95 条 tick，CSV 落盘正常。进程会在 `api.Release()` 处被 proxychains 挂住，因此外层要套 `timeout`；被 timeout 杀掉返回 124 属正常现象。

#### 新设备 / 其他 Python 版本（3.10 / 3.11 / 3.12）

`udpapi` 的 `libGtjaMdUserApi.so` 是纯 C++ 动态库，与 Python 版本无关；**只有 pybind11 绑定模块需要重编**，所以任何 Python 版本都能用，代价是一次编译。以 3.12 为例：

```bash
# 1) 准备一个独立的 3.12 环境（conda 亦可：conda create -n py312 python=3.12）
python3.12 -m venv ~/gtja-venv
source ~/gtja-venv/bin/activate
python -V                        # 确认是 3.12.x

# 2) 编译依赖
#    注意：Python 3.12 的 venv 默认不再自带 setuptools，必须显式安装；
#    Python 3.12 要求 pybind11 >= 2.11.1，pybind11 3.x 又要求编译器支持 C++17
pip install setuptools 'pybind11>=2.11.1'
g++ --version                    # 需 GCC 7+；Debian/Ubuntu 缺编译器时 apt install build-essential

# 3) 重新编译（务必先删 build/，不要复用仓库里 cp39 的构建产物）
cd pybind_gtja
rm -rf build
python setup.py build_ext --inplace

# 4) 验证
python -c "import gtja_udp_api; print('OK')"   # 打印 OK 即成功
python pull_data.py --help
```

编译生成的文件名会带上当前版本标签，例如 3.12 下是 `gtja_udp_api.cpython-312-x86_64-linux-gnu.so`；它与 3.9 的 `.so` 可以共存，互不影响。

```bash
ls gtja_udp_api*.so
# gtja_udp_api.cpython-39-x86_64-linux-gnu.so     ← 预置的（py39）
# gtja_udp_api.cpython-310-x86_64-linux-gnu.so    ← 为 rqsdk/3.10 编的
# gtja_udp_api.cpython-312-x86_64-linux-gnu.so    ← 3.12 新编的
```

每个解释器只会加载与自己 ABI 标签匹配的那个文件，所以多版本可以长期共存。

之后用 3.12 运行（**不要**再切回 py39，否则又变成 ABI 不匹配）：

```bash
cd pybind_gtja
python pull_data.py --front tcp://183.193.54.200:21002 \
    --user 00000001 --password 88888888 --symbols 600000,688027 --exchange sse
```

常见编译报错对照：

| 报错 | 原因 / 处理 |
|------|------------|
| `No module named 'setuptools'` | 3.12 venv 未自带 setuptools → `pip install setuptools` |
| `Python.h: No such file or directory` | 缺开发头文件 → 装 `python3.12-dev`（或用 conda 环境） |
| `pybind11 requires C++17 or later` | 编译器过旧 → 升级 g++，或改用 `pybind11<3` |
| `找不到 头文件目录: .../udpapi/include` | SDK 路径不对 → 见下文「SDK 位置」，或用 `GTJA_UDPAPI_ROOT` 指定 |

---

## 行情 SDK 依赖（必须先安装）

`pybind_gtja/pull_data.py` **不是纯 Python 实现**，它通过 `gtja_udp_api` 扩展调用国泰君安官方 UDP 行情 SDK（udpapi）。拉取证券行情必须依赖 SDK 提供的 C++ 头文件和动态库：

- 编译扩展时需要 `include/*.h` 和 `libGtjaMdUserApi.so`；
- 运行时扩展会加载 `libGtjaMdUserApi.so`，由它建立行情连接并解析数据。

没有 SDK 文件，扩展既无法编译，也无法导入运行，行情自然拉不到。

### SDK 位置

本仓库已包含 SDK，位于 [`udpapi/`](udpapi/)：

```
udpapi/
├── include/                          # C++ 头文件（编译必需）
│   ├── GtjaMdStructV3.h
│   └── GtjaMdUserApi.h
├── Linux64/
│   ├── gcc9.3.1/libGtjaMdUserApi.so  # 当前使用的动态库
│   └── gcc4.4.7/ ... gcc8.3.1/       # 其他 gcc 版本
├── Win32/  Win64/                    # Windows 库
├── demo/                             # 官方示例
└── UDP行情api使用说明.html            # 官方接口文档
```

**SDK 不需要复制到 `pybind_gtja/` 下**，保持仓库根目录的 `udpapi/` 即可。关键只有两点：

1. `pybind_gtja/setup.py` 中的 `UDPAPI_ROOT` 指向 SDK 根目录；
2. 编译出的扩展能通过 rpath（或 `LD_LIBRARY_PATH`）找到 `libGtjaMdUserApi.so`。

`setup.py` 已按本仓库布局自动定位 SDK，无需修改：

```python
UDPAPI_ROOT = os.getenv("GTJA_UDPAPI_ROOT") or os.path.join(os.path.dirname(ROOT), "udpapi")
# 即 /root/private_data/Market_Data/udpapi
```

编译脚本会在 `Linux64/` 下依次查找 `gcc9.3.1` → `gcc8.3.1` → `gcc7.3.1` → `gcc4.8.5` → `gcc4.4.7`，使用第一个存在 `libGtjaMdUserApi.so` 的目录。SDK 放在别处时可用环境变量覆盖：

```bash
export GTJA_UDPAPI_ROOT=/path/to/udpapi              # SDK 根目录
export GTJA_UDPAPI_LIB_DIR=/path/to/gcc9.3.1         # 指定动态库目录（可选）
```

若目录不存在，编译会立即报错并提示缺失的路径，而不是抛出难懂的编译错误。

### 编译与验证

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate py39
cd pybind_gtja
python setup.py build_ext --inplace

# 确认扩展链接到了仓库内的 SDK
ldd gtja_udp_api*.so | grep GtjaMdUserApi
```

`ldd` 应输出类似：

```
libGtjaMdUserApi.so => /root/private_data/Market_Data/udpapi/Linux64/gcc9.3.1/libGtjaMdUserApi.so
```

如果运行时仍提示找不到动态库：

```bash
export LD_LIBRARY_PATH=/root/private_data/Market_Data/udpapi/Linux64/gcc9.3.1:$LD_LIBRARY_PATH
```

> **换机器 / 换目录后必须重新编译。** 仓库里提交的 `gtja_udp_api.cpython-39-x86_64-linux-gnu.so` 把绝对路径 `/root/private_data/trading/udpapi/...` 写进了 rpath，在新环境下即使能导入也会因找不到动态库而失败。重新编译会按本机实际路径重写 rpath：

```bash
rm -rf pybind_gtja/build
cd pybind_gtja && python setup.py build_ext --inplace
readelf -d gtja_udp_api*.so | grep -Ei 'rpath|runpath'   # 应指向本仓库的 udpapi/Linux64/gcc9.3.1
```

---

## ctp_mdapi.py

继承 `vnpy_ctp.api.MdApi`，不依赖 `MainEngine` / `EventEngine`，完成连接前置、登录、订阅合约并持续打印五档行情。

### 配置

脚本顶部常量：

| 常量 | 说明 |
|------|------|
| `USER_ID` / `PASSWORD` / `BROKER_ID` | CTP 认证信息 |
| `MARKET_DATA_SERVERS` | 行情前置地址列表 |
| `SERVER_INDEX` | 选择列表中的第几个前置 |
| `GOLD_SYMBOL` | 订阅合约，如 `ag2612` |
| `WAIT_TIME` | 连接/登录超时（秒） |

### 运行

CTP 登录回报含中文，运行前需确保系统有中文 locale：

```bash
sudo apt-get install -y locales-all && sudo locale-gen

pip install vnpy_ctp
python ctp_mdapi.py
```

示例输出：

```
[INFO] C locale 已设置为: zh_CN.GB18030
[INFO] 当前使用行情服务器: tcp://101.231.185.21:61213
正在连接行情服务器...
行情服务器连接成功
正在登录行情服务器...
行情服务器登录成功
订阅黄金合约: ag2612
等待行情数据，按 Ctrl+C 退出...

[14:30:00.500] ag2612
  最新价: 7588.0       开盘价: 7590.0       最高价: 7620.0
  最低价: 7565.0       成交量: 123456       持仓量: 234567
  昨结算: 7601.0       昨收盘: 7599.0       均价:   7590.5
  涨停板: 7981.0       跌停板: 7221.0
  五档盘口:
    买1:     7587.0 x 12     | 卖1:     7588.0 x 8
    买2:     7586.0 x 20     | 卖2:     7589.0 x 15
    买3:     7585.0 x 35     | 卖3:     7590.0 x 22
    买4:     7584.0 x 40     | 卖4:     7591.0 x 30
    买5:     7583.0 x 58     | 卖5:     7592.0 x 45
```

首次收到某合约行情时，脚本会额外打印该 tick 的全部非空字段，便于确认可用字段。`Ctrl+C` 退出并调用 `api.exit()`。

---

## pybind_gtja/pull_data.py

通过 pybind11 封装国泰君安官方 C++ 行情 API，**仅用于订阅沪深股票**（上交所/深交所），可将 tick 打印到控制台并写入 CSV。不支持期货、期权及黄金现货合约。

### 前置要求：安装 udpapi SDK

`pull_data.py` 依赖国泰君安官方 UDP 行情 SDK（C++ 头文件 + 动态库）。SDK 已随仓库提供在 [`udpapi/`](udpapi/)，**无需放到 `pybind_gtja/` 下**；路径配置、编译与验证方法见上文「行情 SDK 依赖（必须先安装）」。

### 编译扩展

SDK 准备好后，首次使用需编译 `gtja_udp_api`：

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate py39
cd pybind_gtja
python setup.py build_ext --inplace
```

### 运行

**必须用编译该扩展时所用的同一个 Python 版本**：本机预置扩展是 3.9，所以用 py39；若你在 3.12 环境下按上文重新编译过，就用该 3.12 环境。下文命令中的 `python` 指已激活的环境；不激活时请替换为对应解释器的绝对路径（如 `/opt/conda/envs/py39/bin/python`）。

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate py39
cd pybind_gtja

# 上交所：21002 前置
python pull_data.py \
    --front tcp://183.193.54.200:21002 \
    --user <账号> \
    --password <密码> \
    --symbols 600000,688027 \
    --exchange sse \
    --output sse_ticks.csv \
    --duration 60

# 深交所：42116 前置
python pull_data.py \
    --front tcp://183.63.193.58:42116 \
    --user <账号> \
    --password <密码> \
    --symbols 000001,300750 \
    --exchange szse \
    --output szse_ticks.csv \
    --duration 60
```

本机需使用 py39 解释器并经 proxychains 运行，具体命令见 [pybind_gtja/README.md](pybind_gtja/README.md)。

示例输出：

```
前置地址: tcp://183.193.54.200:21002
账号: 00000001
订阅合约: ['600000', '688027']
CPU 绑定: 1, 关闭 efvi: False
RegisterFront 返回 ConnectID=1
[1] 连接建立，发送登录请求...
[1] 登录成功
前置是否支持订阅: 1
命令行已就绪。输入: sub 股票代码... | unsub 股票代码... | exit
[1] 订阅 600000 成功
[1] 订阅 688027 成功
2026-10-20 14:30:00.123 [1] SSE.600000 20261020 14:30:00.100 last=10.50 vol=12345 bid=10.49/500 ask=10.50/300
2026-10-20 14:30:00.623 [1] SSE.600000 20261020 14:30:00.600 last=10.51 vol=12346 bid=10.50/800 ask=10.51/200
2026-10-20 14:30:00.624 [1] SSE.688027 20261020 14:30:00.600 last=45.20 vol=8890 bid=45.19/120 ask=45.20/96

运行达到 60 秒，退出。共收到 3 条 tick。
```

使用 `--multi` 时，每条行情会展开全部档位：

```
2026-10-20 14:30:00.123 [1] SSE.600000 20261020 14:30:00.100 last=10.50 vol=12345 L1:bid=10.49/500 ask=10.50/300 L2:bid=10.48/1200 ask=10.51/900 L3:bid=10.47/2000 ask=10.52/1500 L4:bid=10.46/3100 ask=10.53/2600 L5:bid=10.45/4400 ask=10.54/3800
```

### 参数

| 参数 | 说明 |
|------|------|
| `--front` | 行情前置地址 |
| `--user` / `--password` | 资金账号 / 密码 |
| `--symbols` | 股票代码（6 位数字），逗号分隔 |
| `--exchange` | 仅 `sse` / `szse`，留空表示由前置判断 |
| `--cpu` | 接收线程绑定的 CPU 核，默认 `1` |
| `--no-efvi` | 关闭 efvi 加速 |
| `--levels` | CSV 保存的盘口档位数，默认 `5` |
| `--multi` | 控制台打印全部档位（默认只打印第 1 档） |
| `--output` | CSV 路径，留空只打印 |
| `--duration` | 运行秒数，`0` 表示持续运行 |

参数也可用同名环境变量提供：`GTJA_FRONT`、`GTJA_USER`、`GTJA_PASSWORD`、`GTJA_SYMBOLS`、`GTJA_EXCHANGE`、`GTJA_CPU`、`GTJA_NO_EFVI`、`GTJA_OUTPUT`、`GTJA_DURATION`、`GTJA_LEVELS`。

### 交互命令

在交互式终端下，运行中可输入：

```
sub 股票代码...      # 动态订阅（仅股票）
unsub 股票代码...    # 动态取消订阅
help / h / ?         # 帮助
exit / quit / q      # 退出
```

非 TTY 环境（重定向、后台运行）会自动禁用命令线程，可用 `Ctrl+C` 或 `--duration` 退出。

### CSV 输出

列依次为：`recv_time`、`conn_id`、`exchange`、`symbol`、`date`、`time`、`milli`、`last_price`、`volume`、`turnover`、`open_interest`，随后按 `--levels` 重复 `bid_price_n`、`bid_volume_n`、`ask_price_n`、`ask_volume_n`，最后为 `status`。

---

## 常见问题

- **CTP locale 崩溃** — 安装 `locales-all` 并执行 `locale-gen`。
- **CTP 连接超时** — 检查 `MARKET_DATA_SERVERS` 中的地址与端口、本机防火墙及网络连通性。
- **`ModuleNotFoundError: No module named 'gtja_udp_api'`** — 九成是 Python 版本与扩展的 ABI 标签不一致（.so 文件名里的 `cpython-3xx`）。Python 3.11/3.12 会直接忽略 `cpython-39` 的 `.so`。`pull_data.py` 现在会打印已有的 `.so` 版本、当前解释器版本和两种解决办法；快速处理：要么切到匹配的解释器，要么在当前解释器下 `rm -rf build && python setup.py build_ext --inplace` 重编。
- **`gtja_udp_api` 找不到 `libGtjaMdUserApi.so`** — 说明 `.so` 的 rpath 指向了不存在的旧路径（如 `/root/private_data/trading/udpapi`），在新环境里重新编译即可重写 rpath；或临时 `export LD_LIBRARY_PATH=/root/private_data/Market_Data/udpapi/Linux64/gcc9.3.1:$LD_LIBRARY_PATH`。
- **登录成功但无行情** — 检查股票代码与交易所是否匹配、是否处于交易时段；只能使用 6 位沪深股票代码，期货合约即使订阅成功也不会收到数据。

## 安全提示

源码中的账号、密码均为测试配置，已进入 git 历史。实际使用请改用环境变量注入并轮换真实凭据，同时将 `*.con`、`*.log`、`__pycache__/`、`build/` 加入 `.gitignore`。

## License

[MIT](LICENSE) © 2026
