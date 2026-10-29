#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demo: 使用 pybind11 封装的国泰君安 UDP 行情 API 快速拉取沪深股票实时 tick 数据。

本工具仅用于股票行情（上交所/深交所），不支持期货合约。

运行前请先编译扩展模块：
    source /opt/conda/etc/profile.d/conda.sh && conda activate py39
    cd /root/private_data/Market_Data/pybind_gtja
    python setup.py build_ext --inplace

用法：
    python pull_data.py --user 00000001 --password 88888888 --symbols 600000,688027
    python pull_data.py --user 00000001 --password 88888888 --symbols 301079.SZ

--front 可省略：未指定时按代码（或 --exchange）自动选择对应交易所的默认前置。
深交所代码请勿连上交所前置——订阅会返回成功，但一条行情都不会推送。

运行中可在控制台输入命令：
    sub 代码1 代码2 ...    # 动态订阅（仅股票）
    unsub 代码1 代码2 ...  # 动态取消订阅
    exit / quit / q        # 退出程序
    help / h / ?           # 显示帮助

环境变量（与命令行等价）：
    GTJA_FRONT, GTJA_USER, GTJA_PASSWORD, GTJA_SYMBOLS, GTJA_EXCHANGE,
    GTJA_CPU, GTJA_NO_EFVI, GTJA_OUTPUT, GTJA_DURATION, GTJA_LEVELS
"""
import argparse
import csv
import glob
import os
import queue
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

try:
    import gtja_udp_api
except ImportError as _exc:
    # 扩展的 ABI 标签必须是 cpython-<版本>，与解释器不一致时 Python 会直接
    # 忽略该 .so 并报 ModuleNotFoundError。这里扫描同目录找出实际编译版本，
    # 给出明确指引（3.9 / 3.12 等任意版本通用）。
    _here = os.path.dirname(os.path.abspath(__file__))
    _built = sorted(
        os.path.basename(_p)[len("gtja_udp_api."):-len(".so")]
        for _p in glob.glob(os.path.join(_here, "gtja_udp_api*.so"))
    )
    _want = "cpython-%d%d" % sys.version_info[:2]

    _lines = [
        "导入 gtja_udp_api 失败：%s" % _exc,
        "当前解释器：Python %s（%s）" % (sys.version.split()[0], sys.executable),
    ]
    if _built:
        _lines.append("目录中已有扩展：%s" % "、".join(_built))
        if not any(_want in _tag for _tag in _built):
            _lines.append(
                "→ ABI 不匹配：已有扩展是为 %s 编译的，当前解释器需要 %s。\n"
                "  方案一：改用匹配的解释器运行（如 /opt/conda/envs/py39/bin/python）；\n"
                "  方案二：在当前解释器下重新编译（推荐，见下）。" % (_built[0], _want)
            )
        else:
            _lines.append(
                "→ ABI 匹配但加载失败，通常是找不到动态库 libGtjaMdUserApi.so，"
                "或编译用的 Python 与当前解释器不是同一个。"
            )
    else:
        _lines.append("→ 未找到任何 gtja_udp_api*.so，需要先编译。")

    _lines.append(
        "在当前解释器下重新编译：\n"
        "  cd pybind_gtja && rm -rf build\n"
        "  pip install 'pybind11>=2.11.1'\n"
        "  python setup.py build_ext --inplace\n"
        "若仍报找不到 libGtjaMdUserApi.so：\n"
        "  export LD_LIBRARY_PATH=<仓库根目录>/udpapi/Linux64/gcc9.3.1:$LD_LIBRARY_PATH"
    )
    sys.exit("\n".join(_lines))


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------
def get_config():
    parser = argparse.ArgumentParser(description="拉取国泰君安 UDP 行情")
    parser.add_argument("--front", default=os.getenv("GTJA_FRONT", ""),
                        help="行情前置地址，留空则按代码/--exchange 自动选择默认前置 "
                             "(SSE tcp://114.94.154.60:21002, SZSE tcp://183.63.193.58:42116)")
    parser.add_argument("--user", default=os.getenv("GTJA_USER", "83607651"), help="资金账号")
    parser.add_argument("--password", default=os.getenv("GTJA_PASSWORD", "88888888"), help="登录密码")
    parser.add_argument("--symbols", default=os.getenv("GTJA_SYMBOLS", "000001"),
                        help="订阅代码（6 位股票 / 8 位沪深期权），逗号分隔，可带 .SH/.SZ 后缀")
    parser.add_argument("--exchange", default=os.getenv("GTJA_EXCHANGE", ""),
                        help="指定交易所: sse/szse（本工具支持股票/ETF 与沪深期权），"
                             "留空则按代码前缀/后缀自动判断")
    parser.add_argument("--cpu", default=os.getenv("GTJA_CPU", "1"), help="绑定 CPU 核")
    parser.add_argument("--no-efvi", action="store_true", default=os.getenv("GTJA_NO_EFVI", "").lower() == "true",
                        help="关闭 efvi 加速")
    parser.add_argument("--output", default=os.getenv("GTJA_OUTPUT", ""), help="输出 csv 文件路径，为空则只打印")
    parser.add_argument("--duration", type=int, default=int(os.getenv("GTJA_DURATION", "0")),
                        help="运行时长（秒），0 表示一直运行")
    parser.add_argument("--levels", type=int, default=int(os.getenv("GTJA_LEVELS", "5")),
                        help="CSV 中保存的盘口档位数，默认 5")
    parser.add_argument("--multi", action="store_true", help="打印时输出全部档位（默认只输出第 1 档）")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 交易所代码 → 可读前缀（仅股票：上交所/深交所）
# ---------------------------------------------------------------------------
EXCHANGE_NAMES = {
    gtja_udp_api._et_sse: "SSE",
    gtja_udp_api._et_szse: "SZSE",
}

RTN_CODE_NAMES = {
    gtja_udp_api._rc_succ: "成功",
    gtja_udp_api._rc_invalid_connid: "非法 ConnectID",
    gtja_udp_api._rc_not_connected: "尚未连接",
    gtja_udp_api._rc_send_request_error: "发送请求失败",
    gtja_udp_api._rc_wrong_param: "参数错误",
    gtja_udp_api._rc_not_login: "尚未登录",
    gtja_udp_api._rc_not_support: "不支持此功能",
}

EXCHANGE_NAME_TO_TYPE = {
    "sse": gtja_udp_api._et_sse,
    "szse": gtja_udp_api._et_szse,
}

EXCHANGE_LABELS = {
    "sse": "上交所(SSE)",
    "szse": "深交所(SZSE)",
}

# 未指定 --front 时使用的默认前置。
DEFAULT_FRONTS = {
    "sse": "tcp://114.94.154.60:21002",   # 也常用 tcp://183.193.54.200:21002
    "szse": "tcp://183.63.193.58:42116",  # 也常用 tcp://183.237.222.224:42116
}

# 实测：21002 只承载上交所，42116 只承载深交所。连错交易所时订阅仍返回
# “成功”，但一条行情都不会推送，所以要在连接前就拦下来。
FRONT_PORT_TO_EXCHANGE = {
    21002: "sse",
    42116: "szse",
}

# 代码后缀（vnpy / 常见行情软件写法），用于显式指定交易所。
SYMBOL_SUFFIX_TO_EXCHANGE = {
    "sh": "sse", "ss": "sse", "sse": "sse",
    "sz": "szse", "szse": "szse",
}


def validate_stock_symbols(symbols: List[str]) -> List[str]:
    """返回不符合合约代码规则的代码（调用前请先去掉 .SH/.SZ 后缀）。

    支持三类：
      * 沪深股票/ETF：6 位数字（600000、000001、510050）
      * 上交所期权：8 位数字且以 1 开头（10011425 = 50ETF 期权）
      * 深交所期权：8 位数字且以 9 开头（90007411 = 创业板ETF 期权）
    """
    def ok(s: str) -> bool:
        if not s.isdigit():
            return False
        return len(s) == 6 or (len(s) == 8 and s[0] in ("1", "9"))

    return [s for s in symbols if not ok(s)]


def normalize_symbols(raw_symbols: List[str]):
    """去掉 .SH/.SZ 后缀，返回 (纯代码列表, {代码: 后缀指定的交易所})。

    例：['301079.SZ', '600000'] -> (['301079', '600000'], {'301079': 'szse'})
    """
    symbols: List[str] = []
    suffix_exchange = {}
    for raw in raw_symbols:
        code, _, suffix = raw.partition(".")
        code = code.strip()
        if not code:
            continue
        symbols.append(code)
        suffix = suffix.strip().lower()
        if not suffix:
            continue
        exch = SYMBOL_SUFFIX_TO_EXCHANGE.get(suffix)
        if exch:
            suffix_exchange[code] = exch
        else:
            print(f"警告: 忽略无法识别的后缀 .{suffix}（仅支持 .SH/.SS/.SZ），按代码前缀判断")
    return symbols, suffix_exchange


def infer_exchange(symbol: str) -> Optional[str]:
    """按代码前缀推断交易所，无法确定时返回 None。

      * 上交所：5xxxxx / 6xxxxx（股票、ETF）、9xxxxx（900 B 股）、
        8 位 1 开头（50ETF 期权等）
      * 深交所：0xxxxx / 2xxxxx / 3xxxxx（股票、B 股、创业板）、
        8 位 9 开头（创业板ETF 期权）
    """
    if not symbol.isdigit():
        return None
    if len(symbol) == 8:
        if symbol[0] == "1":
            return "sse"
        if symbol[0] == "9":
            return "szse"
        return None
    if len(symbol) != 6:
        return None
    head = symbol[0]
    if head in ("5", "6", "9"):
        return "sse"
    if head in ("0", "2", "3"):
        return "szse"
    return None


def exchange_of_front(front: str) -> Optional[str]:
    """按端口识别已知前置所属交易所；未知前置返回 None。"""
    try:
        port = int(front.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        return None
    return FRONT_PORT_TO_EXCHANGE.get(port)


def resolve_exchange(symbols: List[str], suffix_exchange, explicit: str):
    """确定本次连接的交易所，返回 'sse'/'szse'/None。

    explicit 来自 --exchange；为空时按后缀/代码前缀推断。一台前置只承载一个
    交易所，推断出多个交易所时抛出 ValueError（需分成两次运行）。
    """
    if explicit:
        conflicts = [s for s, e in suffix_exchange.items() if e != explicit]
        if conflicts:
            raise ValueError(
                f"--exchange {explicit} 与代码后缀不一致: {', '.join(conflicts)}"
            )
        return explicit

    by_exchange = {}
    for s in symbols:
        e = suffix_exchange.get(s) or infer_exchange(s)
        if e:
            by_exchange.setdefault(e, []).append(s)
    if not by_exchange:
        return None
    if len(by_exchange) > 1:
        detail = "；".join(
            f"{EXCHANGE_LABELS[e]}: {','.join(v)}" for e, v in by_exchange.items()
        )
        raise ValueError(
            f"本次订阅同时包含多个交易所的代码（{detail}）。"
            "一台前置只承载一个交易所，请分别运行或显式指定 --exchange/--front"
        )
    return next(iter(by_exchange))


def build_instruments(symbols: List[str], exchange: str = ""):
    """构建订阅结构体数组；exchange 为空时按代码前缀逐个推断交易所。"""
    insts = []
    for s in symbols:
        exch = (exchange or infer_exchange(s) or "").lower()
        inst = gtja_udp_api.GtjaMdSpecificInstrumentField()
        inst.ExchangeType = EXCHANGE_NAME_TO_TYPE.get(exch, gtja_udp_api._et_unset)
        inst.InstrumentID = s
        insts.append(inst)
    return insts


# ---------------------------------------------------------------------------
# SPI 实现
# ---------------------------------------------------------------------------
class DataSpi(gtja_udp_api.PySpi):
    def __init__(self, api: gtja_udp_api.GtjaMdUserApi, cfg):
        super().__init__()
        self.api = api
        self.cfg = cfg
        self.connected_event = threading.Event()
        self.logged_in_event = threading.Event()
        self.tick_queue: queue.Queue[dict] = queue.Queue()
        self.csv_writer = None
        self.csv_file = None
        self._csv_lock = threading.Lock()
        self._init_csv()

        # 绑定回调
        self.on_front_connected = self._on_front_connected
        self.on_front_disconnected = self._on_front_disconnected
        self.on_rsp_error = self._on_rsp_error
        self.on_rsp_user_login = self._on_rsp_user_login
        self.on_rtn_depth_snapshot = self._on_rtn_depth_snapshot
        self.on_rsp_last_snapshot = self._on_rsp_last_snapshot
        self.on_rsp_sub_market_data = self._on_rsp_sub_market_data
        self.on_rsp_unsub_market_data = self._on_rsp_unsub_market_data

    def _init_csv(self):
        if not self.cfg.output:
            return
        self.csv_file = open(self.cfg.output, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        headers = [
            "recv_time", "conn_id", "exchange", "symbol", "date", "time", "milli",
            "last_price", "volume", "turnover", "open_interest",
        ]
        for i in range(1, self.cfg.levels + 1):
            headers.extend([f"bid_price_{i}", f"bid_volume_{i}", f"ask_price_{i}", f"ask_volume_{i}"])
        headers.append("status")
        # SDK V3.7.1.1 新增字段；旧版 SDK 下恒为空
        headers.extend(["dyn_ref_price", "vir_match", "iopv"])
        self.csv_writer.writerow(headers)
        self.csv_file.flush()

    def _on_front_connected(self, conn_id: int):
        print(f"[{conn_id}] 连接建立，发送登录请求...")
        self.connected_event.set()
        self.api.ReqUserLogin(self.cfg.user, self.cfg.password, 0, conn_id)

    def _on_front_disconnected(self, reason: int, conn_id: int):
        print(f"[{conn_id}] 连接断开，原因: 0x{reason:04X}")
        self.connected_event.clear()
        self.logged_in_event.clear()

    def _on_rsp_error(self, rsp_info, request_id: int, is_last: bool, conn_id: int):
        if rsp_info:
            print(f"[{conn_id}] 错误响应 ErrorID={rsp_info.ErrorID}, Msg={rsp_info.ErrorMsg}")
        else:
            print(f"[{conn_id}] 错误响应 (NULL)")

    def _on_rsp_user_login(self, rsp_user_login, rsp_info, request_id: int, is_last: bool, conn_id: int):
        if rsp_info and rsp_info.ErrorID:
            print(f"[{conn_id}] 登录失败: {rsp_info.ErrorID} - {rsp_info.ErrorMsg}")
            return
        print(f"[{conn_id}] 登录成功")
        self.logged_in_event.set()

    def _on_rtn_depth_snapshot(self, instrument, stamp, trade_info, base_info,
                               static_info, mbl_length: int, mbl, status, extra,
                               conn_id: int):
        if not instrument:
            return

        symbol = instrument.InstrumentID
        exchange_code = instrument.ExchangeType
        exchange = EXCHANGE_NAMES.get(exchange_code, f"ET{exchange_code}")

        # 时间戳解析
        dt_str = ""
        time_str = ""
        milli = ""
        if stamp:
            d = stamp.Date
            t = stamp.Time
            dt_str = f"{d.Year:04d}{d.Month:02d}{d.Day:02d}"
            time_str = f"{t.Hour:02d}:{t.Minite:02d}:{t.Seccond:02d}"
            milli = f"{t.MilliSec:03d}"

        # 成交信息
        last_price = trade_info.LastPrice if trade_info else None
        volume = trade_info.Volume if trade_info else None
        turnover = trade_info.Turnover if trade_info else None
        open_interest = trade_info.OpenInterest if trade_info else None

        # 盘口信息
        bids = []
        if mbl and mbl_length > 0:
            for i in range(mbl_length):
                bids.append({
                    "bid_price": mbl[i].BidPrice,
                    "bid_volume": mbl[i].BidVolume,
                    "ask_price": mbl[i].AskPrice,
                    "ask_volume": mbl[i].AskVolume,
                })

        # 合约状态
        status_str = ""
        if status:
            status_str = "".join(status.InstrumentStauts)

        # SDK V3.7.1.1 扩展字段（动态参考价/虚拟匹配量/IOPV）
        dyn_ref_price = extra.DynRefPrice if extra else None
        vir_match = extra.VirMatch if extra else None
        iopv = extra.IOPV if extra else None

        tick = {
            "recv_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "conn_id": conn_id,
            "exchange": exchange,
            "symbol": symbol,
            "date": dt_str,
            "time": time_str,
            "milli": milli,
            "last_price": last_price,
            "volume": volume,
            "turnover": turnover,
            "open_interest": open_interest,
            "bids": bids,
            "status": status_str.strip(),
            "dyn_ref_price": dyn_ref_price,
            "vir_match": vir_match,
            "iopv": iopv,
        }

        self.tick_queue.put(tick)

        # 打印
        line = (
            f"{tick['recv_time']} [{conn_id}] {exchange}.{symbol} {dt_str} {time_str}.{milli} "
            f"last={last_price} vol={volume}"
        )
        if bids:
            if self.cfg.multi:
                for i, b in enumerate(bids[:self.cfg.levels], 1):
                    line += (
                        f" L{i}:bid={b['bid_price']}/{b['bid_volume']} "
                        f"ask={b['ask_price']}/{b['ask_volume']}"
                    )
            else:
                b = bids[0]
                line += f" bid={b['bid_price']}/{b['bid_volume']} ask={b['ask_price']}/{b['ask_volume']}"
        if status_str.strip():
            line += f" status={status_str.strip()}"
        if extra:
            line += f" ref={dyn_ref_price} vmatch={vir_match} iopv={iopv}"
        print(line)

        # 写入 CSV（写入全部 levels 档）
        if self.csv_writer:
            row = [
                tick["recv_time"], conn_id, exchange, symbol, dt_str, time_str, milli,
                last_price, volume, turnover, open_interest,
            ]
            for i in range(self.cfg.levels):
                if i < len(bids):
                    b = bids[i]
                    row.extend([b['bid_price'], b['bid_volume'], b['ask_price'], b['ask_volume']])
                else:
                    row.extend([None, None, None, None])
            row.append(status_str.strip())
            row.extend([dyn_ref_price, vir_match, iopv])
            with self._csv_lock:
                self.csv_writer.writerow(row)
                self.csv_file.flush()

    def _on_rsp_last_snapshot(self, snapshot, conn_id: int):
        if snapshot:
            print(f"[{conn_id}] 快照 {snapshot.InstrumentID}: last={snapshot.LastPrice} vol={snapshot.Volume}")

    def _on_rsp_sub_market_data(self, instrument, rsp_info, request_id: int, conn_id: int):
        if instrument:
            if rsp_info and rsp_info.ErrorID:
                print(f"[{conn_id}] 订阅 {instrument.InstrumentID} 失败: {rsp_info.ErrorMsg}")
            else:
                print(f"[{conn_id}] 订阅 {instrument.InstrumentID} 成功")

    def _on_rsp_unsub_market_data(self, instrument, rsp_info, request_id: int, conn_id: int):
        if instrument:
            if rsp_info and rsp_info.ErrorID:
                print(f"[{conn_id}] 取消订阅 {instrument.InstrumentID} 失败: {rsp_info.ErrorMsg}")
            else:
                print(f"[{conn_id}] 取消订阅 {instrument.InstrumentID} 成功")

    def close(self):
        if self.csv_file:
            self.csv_file.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    cfg = get_config()
    cfg.exchange = cfg.exchange.strip().lower()
    if cfg.exchange and cfg.exchange not in EXCHANGE_NAME_TO_TYPE:
        print("错误: 本工具仅支持股票，--exchange 只能为 sse 或 szse")
        sys.exit(2)

    if not cfg.user or not cfg.password:
        print("错误: 必须提供 --user 和 --password")
        sys.exit(1)

    raw_symbols = [s.strip() for s in cfg.symbols.split(",") if s.strip()]
    symbols, suffix_exchange = normalize_symbols(raw_symbols)
    invalid = validate_stock_symbols(symbols)
    if invalid:
        print(f"错误: 仅支持 6 位股票代码或 8 位沪深期权代码，不支持: {', '.join(invalid)}")
        sys.exit(2)
    if not symbols:
        print("警告: 未指定订阅合约，登录后不会收到行情。使用 --symbols 指定，逗号分隔。")

    # 交易所：--exchange 优先，否则按 .SH/.SZ 后缀或代码前缀推断
    try:
        exchange = resolve_exchange(symbols, suffix_exchange, cfg.exchange)
    except ValueError as exc:
        print(f"错误: {exc}")
        sys.exit(2)

    # 前置：未指定时按交易所选默认前置；指定了就校验和交易所是否匹配。
    # 连错交易所不会报错，只是永远收不到该代码的行情，所以这里必须先拦。
    if cfg.front:
        front_exchange = exchange_of_front(cfg.front)
        if exchange and front_exchange and front_exchange != exchange:
            print(
                f"错误: --front {cfg.front} 是{EXCHANGE_LABELS[front_exchange]}前置，"
                f"但订阅代码属于{EXCHANGE_LABELS[exchange]}（{', '.join(symbols)}）。\n"
                f"  改用{EXCHANGE_LABELS[exchange]}前置: --front {DEFAULT_FRONTS[exchange]}\n"
                f"  或省略 --front，由代码自动选择（默认 {DEFAULT_FRONTS[exchange]}）"
            )
            sys.exit(2)
        if exchange is None:
            exchange = front_exchange
    else:
        if exchange is None:
            exchange = "sse"
            print(f"警告: 无法从订阅代码推断交易所，默认连接{EXCHANGE_LABELS[exchange]}前置")
        cfg.front = DEFAULT_FRONTS[exchange]
    cfg.exchange = exchange or ""

    print(f"前置地址: {cfg.front}" + (f"（{EXCHANGE_LABELS[cfg.exchange]}）" if cfg.exchange else ""))
    print(f"账号: {cfg.user}")
    print(f"订阅合约: {symbols}")
    print(f"CPU 绑定: {cfg.cpu}, 关闭 efvi: {cfg.no_efvi}")

    # 创建 API
    api = gtja_udp_api.GtjaMdUserApi("gtja_udp.log")
    spi = DataSpi(api, cfg)
    api.RegisterSpi(spi)

    # 配置
    api.SetConfig("cpu", cfg.cpu)
    if cfg.no_efvi:
        api.SetConfig("efvi", "false")

    # 注册行情源并启动
    conn_id = api.RegisterFront(cfg.front)
    print(f"RegisterFront 返回 ConnectID={conn_id}")
    if conn_id < 0:
        print("RegisterFront 失败")
        sys.exit(1)

    api.Init()

    # 等待连接+登录（带超时）
    if not spi.connected_event.wait(timeout=10):
        print("错误: 10 秒内未连接上行情前置")
        sys.exit(1)
    if not spi.logged_in_event.wait(timeout=10):
        print("错误: 10 秒内未完成登录")
        sys.exit(1)

    # 查询是否支持订阅
    supports_sub = api.QueryFunction(gtja_udp_api._FF_SUPPORT_SUB_MD, conn_id)
    print(f"前置是否支持订阅: {supports_sub}")

    # 订阅合约
    subscribed_symbols = set(symbols)
    if symbols:
        if supports_sub:
            insts = build_instruments(symbols, cfg.exchange)
            ret = api.ReqSubMarketData(insts, 0, conn_id)
            if ret != gtja_udp_api._rc_succ:
                print(f"ReqSubMarketData 返回错误码: {ret} ({RTN_CODE_NAMES.get(ret, '未知')})")
        else:
            print("当前模式（组播/广播）不支持订阅，行情将自动推送")

    # -----------------------------------------------------------------------
    # 交互式命令线程：支持 sub / unsub / exit
    # -----------------------------------------------------------------------
    stop_event = threading.Event()
    api_call_lock = threading.Lock()

    def _send_sub(raw_syms: list):
        if not raw_syms:
            return
        syms, live_suffix = normalize_symbols(raw_syms)
        invalid = validate_stock_symbols(syms)
        if invalid:
            print(f"仅支持 6 位股票代码或 8 位沪深期权代码，已忽略: {', '.join(invalid)}")
            syms = [s for s in syms if s not in invalid]
            if not syms:
                return
        # 一台前置只承载一个交易所：动态订阅别所代码会“成功”但永远收不到行情
        for s in syms:
            e = live_suffix.get(s) or infer_exchange(s)
            if e and cfg.exchange and e != cfg.exchange:
                print(
                    f"警告: {s} 属于{EXCHANGE_LABELS[e]}，当前连接的是"
                    f"{EXCHANGE_LABELS[cfg.exchange]}前置，订阅成功也不会有行情推送"
                )
        insts = build_instruments(syms, cfg.exchange)
        with api_call_lock:
            ret = api.ReqSubMarketData(insts, 0, conn_id)
        if ret != gtja_udp_api._rc_succ:
            print(f"ReqSubMarketData 返回错误码: {ret} ({RTN_CODE_NAMES.get(ret, '未知')})")
        else:
            subscribed_symbols.update(syms)
            print(f"已发送订阅: {syms}")

    def _send_unsub(raw_syms: list):
        if not raw_syms:
            return
        syms, _ = normalize_symbols(raw_syms)
        insts = build_instruments(syms, cfg.exchange)
        with api_call_lock:
            ret = api.ReqUnSubMarketData(insts, 0, conn_id)
        if ret != gtja_udp_api._rc_succ:
            print(f"ReqUnSubMarketData 返回错误码: {ret} ({RTN_CODE_NAMES.get(ret, '未知')})")
        else:
            subscribed_symbols.difference_update(syms)
            print(f"已发送取消订阅: {syms}")

    def command_loop():
        print("命令行已就绪。输入: sub 股票代码... | unsub 股票代码... | exit")
        while not stop_event.is_set():
            try:
                line = input().strip()
            except EOFError:
                # 非交互式环境或输入关闭，直接退出命令线程
                break
            except Exception as e:
                print(f"读取命令出错: {e}")
                break
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]
            if cmd in ("exit", "quit", "q"):
                print("收到退出命令...")
                stop_event.set()
                break
            elif cmd in ("sub", "subscribe"):
                _send_sub(args)
            elif cmd in ("unsub", "unsubscribe"):
                _send_unsub(args)
            elif cmd in ("help", "h", "?"):
                print("命令: sub 股票代码... | unsub 股票代码... | exit | help（仅支持沪深股票）")
            else:
                print(f"未知命令: {cmd}。输入 help 查看支持命令。")

    if sys.stdin.isatty():
        cmd_thread = threading.Thread(target=command_loop, daemon=True)
        cmd_thread.start()
    else:
        print("非交互式环境，命令行功能已禁用（可用 Ctrl+C 或 --duration 退出）")

    # 运行主循环
    start = time.time()
    tick_count = 0
    try:
        while not stop_event.is_set():
            try:
                tick = spi.tick_queue.get(timeout=1)
                tick_count += 1
            except queue.Empty:
                pass

            if cfg.duration > 0 and (time.time() - start) >= cfg.duration:
                print(f"运行达到 {cfg.duration} 秒，退出。共收到 {tick_count} 条 tick。")
                if tick_count == 0 and symbols and supports_sub:
                    print(
                        "提示: 订阅已发送但没有收到行情，常见原因：\n"
                        f"  1) 前置与代码交易所不匹配——当前 {cfg.front}"
                        f"（{EXCHANGE_LABELS.get(cfg.exchange, '未知')}），代码 {', '.join(symbols)}；"
                        "一台前置只承载一个交易所；\n"
                        "  2) 非交易时段：订阅后只会回放最后一笔快照，休市时无推送；\n"
                        "  3) 代码有误，或该账号无此品种权限。"
                    )
                break
    except KeyboardInterrupt:
        print(f"\n用户中断。共收到 {tick_count} 条 tick。")
    finally:
        stop_event.set()
        if subscribed_symbols and supports_sub:
            _send_unsub(list(subscribed_symbols))
            time.sleep(0.5)
        api.Release()
        spi.close()


if __name__ == "__main__":
    main()
