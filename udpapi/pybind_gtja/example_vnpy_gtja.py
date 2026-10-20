#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
vn.py 3.x + 国泰君安 UDP 行情 Gateway 使用示例。

运行前请确保：
1. 已激活 py39 环境
2. 已编译 gtja_udp_api 扩展
3. 已安装 vn.py: pip install vnpy

运行:
    source /opt/conda/etc/profile.d/conda.sh && conda activate py39
    python example_vnpy_gtja.py --front tcp://114.94.154.60:21002 --user 00000001 --password 88888888 --symbols cu2501,rb2501 --exchange SHFE
"""
import argparse
import signal
import sys
import time

from vnpy.event import EventEngine
from vnpy.trader.constant import Exchange
from vnpy.trader.event import EVENT_LOG, EVENT_TICK
from vnpy.trader.engine import MainEngine
from vnpy.trader.object import SubscribeRequest

from vnpy_gtja_md import GtjaMdGateway


def parse_args():
    parser = argparse.ArgumentParser(description="vn.py GTJA UDP 行情示例")
    parser.add_argument("--front", default="tcp://114.94.154.60:21002", help="行情前置地址")
    parser.add_argument("--user", default="83607651", help="资金账号") #"83607651" "00000001"
    parser.add_argument("--password", default="88888888", help="登录密码")
    parser.add_argument("--symbols", default="cu2501,rb2501", help="订阅合约，逗号分隔")
    parser.add_argument("--exchange", default="", help="合约交易所，如 SHFE/DCE/CZCE/CFFEX/INE/SSE/SZSE/SGE；股票/不指定可留空")
    parser.add_argument("--cpu", default="1", help="绑定 CPU 核")
    parser.add_argument("--no-efvi", action="store_true", help="关闭 efvi 加速")
    parser.add_argument("--duration", type=int, default=60, help="运行时长(秒)，默认 60")
    return parser.parse_args()


def infer_exchange(symbol: str) -> Exchange:
    """根据合约代码简单推断交易所；无法推断时默认 SHFE。"""
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith("6"):
            return Exchange.SSE
        elif symbol.startswith(("0", "2", "3")):
            return Exchange.SZSE
    return Exchange.SHFE


def main():
    cfg = parse_args()

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(GtjaMdGateway)

    setting = {
        "front": cfg.front,
        "user": cfg.user,
        "password": cfg.password,
        "cpu": cfg.cpu,
        "efvi": "false" if cfg.no_efvi else "true",
        "exchange": cfg.exchange,
    }

    print(f"连接 {cfg.front} ...")

    # 先注册事件监听，避免 connect/subscribe 期间到达的 tick 丢失
    tick_count = 0

    def on_tick(event):
        nonlocal tick_count
        tick_count += 1
        tick = event.data
        print(
            f"{tick.datetime} {tick.vt_symbol} "
            f"last={tick.last_price} vol={tick.volume} "
            f"bid1={tick.bid_price_1}/{tick.bid_volume_1} "
            f"ask1={tick.ask_price_1}/{tick.ask_volume_1}"
        )

    def on_log(event):
        log = event.data
        print(f"[LOG][{log.gateway_name}] {log.msg}")

    event_engine.register(EVENT_TICK, on_tick)
    event_engine.register(EVENT_LOG, on_log)

    main_engine.connect(setting, GtjaMdGateway.default_name)

    # 检查网关连接/登录状态
    gateway = main_engine.get_gateway(GtjaMdGateway.default_name)
    if gateway and gateway.spi:
        print(f"网关 connected={gateway.spi.connected}, logged_in={gateway.spi.logged_in}")
    else:
        print("网关或 SPI 未初始化")

    explicit_exchange: Exchange = None
    if cfg.exchange:
        explicit_exchange = Exchange(cfg.exchange.upper())

    symbols = [s.strip() for s in cfg.symbols.split(",") if s.strip()]
    for symbol in symbols:
        exchange = explicit_exchange or infer_exchange(symbol)
        req = SubscribeRequest(symbol=symbol, exchange=exchange)
        print(f"订阅 {req.vt_symbol}")
        main_engine.subscribe(req, GtjaMdGateway.default_name)

    # 优雅退出
    running = True
    def on_signal(signum, frame):
        nonlocal running
        print("\n收到退出信号...")
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    print(f"开始接收行情，运行 {cfg.duration} 秒...")
    start = time.time()
    try:
        while running:
            time.sleep(0.1)
            if cfg.duration > 0 and (time.time() - start) >= cfg.duration:
                print(f"运行时间到，退出。共收到 {tick_count} 条 tick。")
                break
    finally:
        main_engine.close()
        event_engine.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()

# proxychains4 -f ./proxychains.conf python example_vnpy_gtja.py  --symbols 000001 --duration 60 