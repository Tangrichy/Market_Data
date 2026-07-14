# 国泰君安 UDP 行情 API Python 绑定

基于 pybind11 对官方 C++ API（V3.7.x）做的 Python 封装，用于在 Python 3.9 环境下快速拉取行情 tick 数据。

## 文件说明

| 文件 | 说明 |
|------|------|
| `gtja_udp_api.cpp` | pybind11 C++ 绑定源码 |
| `setup.py` | 编译脚本 |
| `pull_data.py` | Python 拉取数据示例 |

## 环境要求

- Python 3.9（当前使用 conda 环境 `py39`）
- pybind11
- g++（支持 C++11，当前系统为 11.4.0，与 gcc9.3.1 编译的官方库可兼容）

## 编译

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate py39
cd /root/private_data/trading/udpapi/pybind_gtja
python setup.py build_ext --inplace
```

编译成功后会在当前目录生成 `gtja_udp_api*.so`。

## 运行示例

### 命令行

```bash
python pull_data.py \
    --front tcp://127.0.0.1:42116 \
    --user 00000001 \
    --password 88888888 \
    --symbols cu2501,rb2501 \
    --output ticks.csv \
    --duration 60
```

### 环境变量

```bash
export GTJA_FRONT=tcp://127.0.0.1:42116
export GTJA_USER=00000001
export GTJA_PASSWORD=88888888
export GTJA_SYMBOLS=cu2501,rb2501
python pull_data.py
```

## 参数说明

- `--front`: 行情前置地址
- `--user`: 资金账号
- `--password`: 密码
- `--symbols`: 要订阅的合约，逗号分隔
- `--cpu`: 绑定接收线程 CPU 核，默认 `1`
- `--no-efvi`: 关闭 efvi 加速
- `--output`: 输出 csv 文件路径
- `--duration`: 运行时长（秒），默认 `0` 表示一直运行

## 注意事项

1. 当前动态库使用 `/root/private_data/trading/udpapi/Linux64/gcc9.3.1/libGtjaMdUserApi.so`，`setup.py` 已设置 `rpath`。

`GtjaMdUserApi` 在 Python 中直接实例化：

```python
import gtja_udp_api
api = gtja_udp_api.GtjaMdUserApi("api.log")
```

释放时调用 `api.Release()`，或让对象自然析构即可。
2. `setup.py` 已设置 `rpath`，运行时应能自动找到动态库；如仍报找不到库，可手动设置：
   ```bash
   export LD_LIBRARY_PATH=/root/private_data/trading/udpapi/Linux64/gcc9.3.1:$LD_LIBRARY_PATH
   ```
3. 订阅功能仅在 TCP 单播模式下有效，组播/广播模式会自动推送全量行情。
4. `GtjaMdInstrumentFieldV3.InstrumentID` 在 C 头文件中是柔性数组，Python 侧通过只读属性获取完整字符串。
