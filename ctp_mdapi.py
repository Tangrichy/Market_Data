#!/usr/bin/env python
"""
CTP 黄金期货行情测试脚本 v2（基于原生 MdApi，带代理配置）

本文件继承自 test_ctp_gold_tick_v2_mdapi.py，主要改动：
1. 自动注入 HTTP 代理环境变量，解决无直接外网环境下的 CTP 连接问题。
2. 提供多个已验证可用的行情接入点，可通过 SERVER_INDEX 快速切换。
3. 保留原生 MdApi 用法，不依赖 MainEngine / EventEngine。

运行前请确保已安装依赖：
    pip install vnpy_ctp

代理来源：当前 shell 环境变量中的 http_proxy / https_proxy
python test_ctp_gold_tick_v2_mdapi_with_proxy.py
"""

# ============================================================
# 0. 环境初始化（必须在导入 vnpy_ctp 之前设置）
# ============================================================

import os

# 修复 CTP 底层 C++ 库的 locale 错误
# CTP 登录回报含中文，底层依赖 GBK 编码的 locale；必须设置为 zh_CN.GBK
for key in list(os.environ.keys()):
    if key.startswith("LC_"):
        del os.environ[key]

import locale
_locale_set = False
for name in ("zh_CN.GB18030", "zh_CN.gb18030", "zh_CN.GBK", "zh_CN.gbk"):
    try:
        locale.setlocale(locale.LC_ALL, name)
        _locale_set = True
        break
    except Exception as e:
        print(f"[DEBUG] 尝试 locale {name} 失败: {e}")

if not _locale_set:
    print("[ERROR] 无法设置中文 GBK/GB18030 locale，CTP 底层 C++ 库将崩溃。")
    print("        请在 root 权限下执行以下命令安装 locale 后重试：")
    print("          apt-get install -y locales-all")
    print("          locale-gen")
    raise RuntimeError("缺少中文 locale")

os.environ["LANG"] = locale.setlocale(locale.LC_ALL, None)
os.environ["LC_ALL"] = locale.setlocale(locale.LC_ALL, None)
print(f"[INFO] C locale 已设置为: {locale.setlocale(locale.LC_ALL, None)}")

# 代理配置：从当前环境变量读取，若未设置则使用默认值。
# 格式：http://用户名:密码@代理IP:端口
HTTP_PROXY: str = os.environ.get(
    "http_proxy",
    "http://scnz82pdal:07979e10@10.1.4.13:3120"
)
HTTPS_PROXY: str = os.environ.get(
    "https_proxy",
    "http://scnz82pdal:07979e10@10.1.4.13:3120"
)

os.environ["http_proxy"] = HTTP_PROXY
os.environ["https_proxy"] = HTTPS_PROXY
os.environ["HTTP_PROXY"] = HTTP_PROXY
os.environ["HTTPS_PROXY"] = HTTPS_PROXY

print(f"[INFO] 已设置 HTTP 代理: {HTTP_PROXY}")


import time
from threading import Condition

from vnpy_ctp.api import MdApi


# ============================================================
# 1. CTP 登录认证信息
# ============================================================
USER_ID: str = "0000"                   # CTP 用户名
PASSWORD: str = "0000"                  # CTP 密码
BROKER_ID: str = "7090"                 # 经纪商代码

# ============================================================
# 2. 行情服务器地址列表
#    以下地址已通过 10.1.4.13:3120 代理验证 61213 端口可达。
#    通过修改 SERVER_INDEX 即可切换接入点。
# ============================================================
MARKET_DATA_SERVERS: list[str] = [
    # 上海电信站点1
    "tcp://101.231.185.21:61213",
    # 上海电信站点2
    "tcp://101.231.185.57:61213",
    "tcp://101.231.185.58:61213",
    "tcp://101.231.185.59:61213",
    "tcp://101.231.185.60:61213",
    # 上海电信站点3
    "tcp://180.166.83.72:61213",
    "tcp://180.166.83.73:61213",
    "tcp://180.166.83.74:61213",
    "tcp://180.166.83.75:61213",
    # 上海联通站点1
    "tcp://140.206.102.76:61213",
    "tcp://140.206.102.77:61213",
    "tcp://140.206.102.78:61213",
    "tcp://112.65.132.105:61213",
    # 上海联通站点2
    "tcp://112.65.132.21:61213",
    "tcp://112.65.132.22:61213",
    "tcp://112.65.132.23:61213",
    "tcp://112.65.132.25:61213",
]

SERVER_INDEX: int = 0                   # 默认使用第一个接入点

MARKET_DATA_SERVER: str = MARKET_DATA_SERVERS[SERVER_INDEX]

# ============================================================
# 3. 订阅合约与其他参数
# ============================================================
# 订阅的合约代码（上期所黄金期货示例，请根据当前主力合约修改）
GOLD_SYMBOL: str = "ag2608"

# 连接和登录超时时间（秒）
WAIT_TIME: int = 20
# ============================================================


class MyMdApi(MdApi):
    """继承 CTP 行情 API，实现回调函数"""

    def __init__(self) -> None:
        super().__init__()
        self.connect_status: bool = False
        self.login_status: bool = False
        self.callback_done: Condition = Condition()
        self.callback_result: list = []
        self.reqid: int = 0

    def onFrontConnected(self) -> None:
        """行情服务器连接成功回报"""
        print("行情服务器连接成功")
        self.connect_status = True
        with self.callback_done:
            self.callback_done.notify()

    def onFrontDisconnected(self, reason: int) -> None:
        """行情服务器连接断开回报"""
        print(f"行情服务器连接断开，原因: {reason}")
        self.connect_status = False
        self.login_status = False

    def onRspUserLogin(self, data: dict, error: dict, reqid: int, last: bool) -> None:
        """登录请求回报"""
        if error["ErrorID"] == 0:
            print("行情服务器登录成功")
            self.login_status = True
        else:
            print(f"登录失败，错误码: {error['ErrorID']}, 错误信息: {error['ErrorMsg']}")

        self.callback_result = [data, error, reqid, last]
        with self.callback_done:
            self.callback_done.notify()

    def onRspError(self, error: dict, reqid: int, last: bool) -> None:
        """错误回报"""
        print(f"行情接口错误，错误码: {error['ErrorID']}, 错误信息: {error['ErrorMsg']}")
        with self.callback_done:
            self.callback_done.notify()

    def onRspSubMarketData(self, data: dict, error: dict, reqid: int, last: bool) -> None:
        """订阅行情请求回报"""
        if error["ErrorID"] == 0:
            print(f"订阅成功: {data.get('InstrumentID', GOLD_SYMBOL)}")
        else:
            print(f"订阅失败，错误码: {error['ErrorID']}, 错误信息: {error['ErrorMsg']}")

    def onRtnDepthMarketData(self, data: dict) -> None:
        """行情数据推送：打印完整五档及常用字段"""
        update_time: str = data.get("UpdateTime", "")
        update_millisec: int = data.get("UpdateMillisec", 0)
        instrument: str = data.get("InstrumentID", "")

        # 基础字段
        print(f"\n[{update_time}.{update_millisec:03d}] {instrument}")
        print(f"  最新价: {data.get('LastPrice'):<12}  开盘价: {data.get('OpenPrice'):<12}  最高价: {data.get('HighestPrice'):<12}")
        print(f"  最低价: {data.get('LowestPrice'):<12}  成交量: {data.get('Volume'):<12}  持仓量: {data.get('OpenInterest'):<12}")
        print(f"  昨结算: {data.get('PreSettlementPrice'):<12}  昨收盘: {data.get('PreClosePrice'):<12}  均价:   {data.get('AveragePrice'):<12}")
        print(f"  涨停板: {data.get('UpperLimitPrice'):<12}  跌停板: {data.get('LowerLimitPrice'):<12}")

        # 五档买卖盘
        print("  五档盘口:")
        for i in range(1, 6):
            bid_price = data.get(f"BidPrice{i}")
            bid_volume = data.get(f"BidVolume{i}")
            ask_price = data.get(f"AskPrice{i}")
            ask_volume = data.get(f"AskVolume{i}")
            print(f"    买{i}: {bid_price:>10} x {bid_volume:<6} | 卖{i}: {ask_price:>10} x {ask_volume:<6}")

        # 调试：第一次收到行情时打印所有字段名和值，方便查看还有什么可用数据
        if not getattr(self, "_has_printed_keys", False):
            self._has_printed_keys = True
            print("\n  [DEBUG] 该合约第一次行情的完整字段列表：")
            for key, value in sorted(data.items()):
                # 跳过为 0 或空的字段，减少输出量
                if value not in (0, 0.0, "", None):
                    print(f"    {key}: {value}")


def main() -> None:
    """主函数"""
    # 检查必要参数是否已填写
    required = {
        "USER_ID": USER_ID,
        "PASSWORD": PASSWORD,
        "BROKER_ID": BROKER_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"请先填写以下认证信息: {', '.join(missing)}")

    print(f"[INFO] 当前使用行情服务器: {MARKET_DATA_SERVER}")

    # 创建行情 API 实例
    api: MyMdApi = MyMdApi()

    # 创建 CTP 行情 API
    # 参数为行情流文件保存路径，传空字符串表示使用当前目录
    api.createFtdcMdApi("")

    # 注册行情服务器地址
    api.registerFront(MARKET_DATA_SERVER)

    # 初始化并启动连接
    api.init()

    # 等待行情服务器连接成功
    print("正在连接行情服务器...")
    count: int = 0
    while not api.connect_status:
        time.sleep(1)
        count += 1
        if count >= WAIT_TIME:
            raise TimeoutError("CTP行情服务器连接超时，请检查地址和端口")

    # 发送登录请求
    api.reqid += 1
    login_req = {
        "UserID": USER_ID,
        "Password": PASSWORD,
        "BrokerID": BROKER_ID,
    }
    print("正在登录行情服务器...")
    api.reqUserLogin(login_req, api.reqid)

    # 等待登录回报
    with api.callback_done:
        api.callback_done.wait(WAIT_TIME)

    # 检查登录结果
    error: dict = api.callback_result[1]
    if error["ErrorID"] != 0:
        raise RuntimeError(f"CTP行情服务器登录失败，错误代码：{error['ErrorID']}，{error['ErrorMsg']}")

    if not api.login_status:
        raise RuntimeError("CTP行情服务器登录失败，未知错误")

    # 订阅黄金合约
    print(f"订阅黄金合约: {GOLD_SYMBOL}")
    api.subscribeMarketData(GOLD_SYMBOL)

    # 保持主线程运行，持续接收行情
    print("等待行情数据，按 Ctrl+C 退出...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到退出信号，正在关闭...")
    finally:
        api.exit()


if __name__ == "__main__":
    main()
