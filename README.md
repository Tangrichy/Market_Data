# Market_Data

期货与证券实时行情接入工具集，提供两个可直接运行的行情脚本：

- [ctp_mdapi.py](ctp_mdapi.py) — 基于 CTP 的期货行情
- [pybind_gtja/pull_data.py](pybind_gtja/pull_data.py) — 基于国泰君安 UDP 行情的期货、股票与黄金现货行情

## 环境要求

- Python 3.9（`gtja_udp_api` 扩展按 `cpython-39` 编译）
- `pip install vnpy_ctp`、`pip install pybind11`、g++（C++11）
- Linux x86_64，CTP 需要中文 locale（GBK/GB18030）
- 使用国泰君安 UDP 行情前，需先安装 udpapi 包（见下文 `pull_data.py` 一节）

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

通过 pybind11 封装国泰君安官方 C++ 行情 API，支持订阅期货、沪深股票及黄金现货合约，可将 tick 打印到控制台并写入 CSV。

### 前置要求：安装 udpapi

`pull_data.py` 依赖国泰君安官方 UDP 行情 API 包（udpapi）。使用前需先安装该包，将其放到 `/root/private_data/trading/udpapi`，并确认以下文件存在：

```
/root/private_data/trading/udpapi/
├── include/
│   ├── GtjaMdStructV3.h
│   └── GtjaMdUserApi.h
└── Linux64/gcc9.3.1/
    └── libGtjaMdUserApi.so
```

若安装在其他路径，需修改 [setup.py](pybind_gtja/setup.py) 中的 `UDPAPI_ROOT`。

### 编译扩展

udpapi 安装完成后，首次使用需编译 `gtja_udp_api`：

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate py39
cd pybind_gtja
python setup.py build_ext --inplace
```

### 运行

```bash
cd pybind_gtja
python pull_data.py \
    --front tcp://<host>:<port> \
    --user <账号> \
    --password <密码> \
    --symbols cu2501,rb2501 \
    --exchange SHFE \
    --output ticks.csv \
    --duration 60
```

示例输出：

```
前置地址: tcp://114.94.154.60:21002
账号: 00000001
订阅合约: ['cu2501', 'rb2501']
CPU 绑定: 1, 关闭 efvi: False
RegisterFront 返回 ConnectID=1
[1] 连接建立，发送登录请求...
[1] 登录成功
前置是否支持订阅: 1
命令行已就绪。输入: sub 合约1 合约2 | unsub 合约1 合约2 | exit
[1] 订阅 cu2501 成功
[1] 订阅 rb2501 成功
2026-10-20 14:30:00.123 [1] SHFE.cu2501 20261020 14:30:00.100 last=76540.0 vol=12345 bid=76530.0/5 ask=76540.0/3
2026-10-20 14:30:00.623 [1] SHFE.cu2501 20261020 14:30:00.600 last=76550.0 vol=12346 bid=76540.0/8 ask=76550.0/2
2026-10-20 14:30:00.624 [1] SHFE.rb2501 20261020 14:30:00.600 last=3288.0 vol=8890 bid=3287.0/120 ask=3288.0/96

运行达到 60 秒，退出。共收到 3 条 tick。
```

使用 `--multi` 时，每条行情会展开全部档位：

```
2026-10-20 14:30:00.123 [1] SHFE.cu2501 20261020 14:30:00.100 last=76540.0 vol=12345 L1:bid=76530.0/5 ask=76540.0/3 L2:bid=76520.0/12 ask=76550.0/9 L3:bid=76510.0/20 ask=76560.0/15 L4:bid=76500.0/31 ask=76570.0/26 L5:bid=76490.0/44 ask=76580.0/38
```

### 参数

| 参数 | 说明 |
|------|------|
| `--front` | 行情前置地址 |
| `--user` / `--password` | 资金账号 / 密码 |
| `--symbols` | 订阅合约，逗号分隔 |
| `--exchange` | `sse` / `szse` / `shfe` / `dce` / `czce` / `cffex` / `ine` / `sge`，留空表示不指定 |
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
sub 资产1 资产2      # 动态订阅
unsub 资产1 资产2    # 动态取消订阅
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
- **`gtja_udp_api` 导入失败** — 确认 Python 3.9、在 `pybind_gtja/` 目录下运行；仍找不到动态库时设置 `LD_LIBRARY_PATH` 指向 SDK 的 `Linux64/gcc9.3.1`。
- **登录成功但无行情** — 检查合约与交易所是否匹配、是否处于交易时段；TCP 单播模式需订阅，组播/广播模式自动推送全量。

## 安全提示

源码中的账号、密码均为测试配置，已进入 git 历史。实际使用请改用环境变量注入并轮换真实凭据，同时将 `*.con`、`*.log`、`__pycache__/`、`build/` 加入 `.gitignore`。

## License

[MIT](LICENSE) © 2026
