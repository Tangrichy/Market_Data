#!/usr/bin/env python
"""
CTP 行情前置直连测试

对 ctp_mdapi.py 中 MARKET_DATA_SERVERS 列出的每个地址直接发起 TCP 连接，
不使用任何代理（socket 直连，忽略 http_proxy 等环境变量），不做 CTP 登录。

结果含义：
    CONNECTED  三次握手成功，端口有服务监听
    TIMEOUT    超时，无法判断对端是否存在（可能被防火墙丢弃或路由黑洞）
    REFUSED    收到 RST，说明路径可达但端口未开放
    其他       具体 socket 错误类型

注意：CONNECTED 只代表 TCP 层连通，不代表 CTP 应用可用。

用法：
    python test_ctp_direct.py
    python test_ctp_direct.py --timeout 5 --workers 16
    python test_ctp_direct.py --from-file other.py

退出码：0 = 全部 TCP 连接成功；1 = 存在失败；2 = 配置/参数错误。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import socket
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG_FILE: Path = Path(__file__).with_name("ctp_mdapi.py")
DEFAULT_TIMEOUT: float = 10.0
DEFAULT_WORKERS: int = 8

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Endpoint:
    label: str
    host: str
    port: int


@dataclass
class Result:
    endpoint: Endpoint
    ok: bool
    detail: str
    elapsed: float


def parse_endpoint(raw: str) -> Endpoint:
    """把 tcp://host:port 解析成 Endpoint，兼容不带 scheme 的写法。"""
    text = raw.strip()
    if "://" not in text:
        text = f"tcp://{text}"

    parsed = urlparse(text)
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"无法解析地址: {raw!r}")

    return Endpoint(label=raw, host=parsed.hostname, port=parsed.port)


def load_servers(path: Path) -> list[str]:
    """
    从源码中静态提取 MARKET_DATA_SERVERS，不执行目标模块。

    避免 import ctp_mdapi 的副作用（改 locale、导入 vnpy_ctp、设置代理环境
    变量），同时保证地址列表只有一份来源。
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    for node in ast.walk(tree):
        # MARKET_DATA_SERVERS = [...] 或 MARKET_DATA_SERVERS: list[str] = [...]
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "MARKET_DATA_SERVERS":
                    if node.value is None:
                        continue
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, list) or not value:
                        raise ValueError("MARKET_DATA_SERVERS 不是非空列表")
                    return [str(item) for item in value]

    raise ValueError(f"{path} 中未找到 MARKET_DATA_SERVERS 定义")


def describe_error(exc: OSError) -> str:
    if isinstance(exc, socket.timeout):
        return "TIMEOUT"
    if isinstance(exc, ConnectionRefusedError):
        return "REFUSED"
    if isinstance(exc, ConnectionResetError):
        return "RESET"
    if isinstance(exc, socket.gaierror):
        return "DNS_FAIL"
    return type(exc).__name__


def check_direct(endpoint: Endpoint, timeout: float, retries: int) -> Result:
    """直连目标端口。"""
    last = Result(endpoint=endpoint, ok=False, detail="NO_ATTEMPT", elapsed=0.0)

    for _ in range(retries + 1):
        start = time.perf_counter()
        sock = None
        try:
            sock = socket.create_connection((endpoint.host, endpoint.port), timeout=timeout)
            return Result(
                endpoint=endpoint,
                ok=True,
                detail="CONNECTED",
                elapsed=time.perf_counter() - start,
            )
        except OSError as exc:
            last = Result(
                endpoint=endpoint,
                ok=False,
                detail=describe_error(exc),
                elapsed=time.perf_counter() - start,
            )
        finally:
            if sock is not None:
                sock.close()

    return last


def display_width(text: str) -> int:
    """按终端显示宽度计数，中文算 2 列，忽略 ANSI 颜色转义。"""
    text = ANSI_RE.sub("", text)
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def colorize(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    codes = {"green": "32", "red": "31", "yellow": "33"}
    return f"\033[{codes[color]}m{text}\033[0m"


def print_results(results: list[Result], use_color: bool) -> None:
    label_width = max(display_width(r.endpoint.label) for r in results)
    detail_width = max(display_width(r.detail) for r in results)

    header = f"{'#':>3}  {pad('地址', label_width)}  {pad('结果', detail_width)}  {'耗时':>8}"
    print()
    print(header)
    print("-" * (display_width(header) + 2))

    for index, result in enumerate(results, start=1):
        detail = colorize(result.detail, "green" if result.ok else "red", use_color)
        elapsed = f"{result.elapsed * 1000:.0f} ms" if result.ok else "-"
        print(
            f"{index:>3}  {pad(result.endpoint.label, label_width)}  "
            f"{pad(detail, detail_width)}  {elapsed:>8}"
        )

    ok_count = sum(1 for r in results if r.ok)
    print("-" * (display_width(header) + 2))
    if ok_count == len(results):
        print(colorize(
            f"结果: {len(results)} 个地址的 TCP 连接全部成功", "green", use_color
        ))
    else:
        print(colorize(
            f"结果: 共 {len(results)} 个地址, TCP 连接成功 {ok_count}, "
            f"失败 {len(results) - ok_count}",
            "red", use_color,
        ))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="直连测试 CTP 行情前置的 TCP 连通性（不走代理、不做登录）",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
        help=f"从哪个文件读取 MARKET_DATA_SERVERS（默认: {DEFAULT_CONFIG_FILE.name}）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"单次连接超时秒数（默认: {DEFAULT_TIMEOUT:g}）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"并发数（默认: {DEFAULT_WORKERS}）",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help="失败后的额外重试次数（默认: 0）",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用彩色输出",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.timeout <= 0:
        print("[ERROR] --timeout 必须大于 0", file=sys.stderr)
        return 2
    if args.workers <= 0:
        print("[ERROR] --workers 必须大于 0", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("[ERROR] --retries 不能为负数", file=sys.stderr)
        return 2

    try:
        servers = load_servers(args.from_file)
        endpoints = [parse_endpoint(raw) for raw in servers]
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"[ERROR] 读取配置失败: {exc}", file=sys.stderr)
        return 2

    use_color = (
        sys.stdout.isatty()
        and not args.no_color
        and "NO_COLOR" not in os.environ
    )

    print(f"[INFO] 配置文件: {args.from_file.resolve()}")
    print(
        f"[INFO] 直连模式 | 待测地址: {len(endpoints)} 个 | "
        f"超时: {args.timeout:g}s | 并发: {args.workers} | 重试: {args.retries}"
    )

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(args.workers, len(endpoints))) as executor:
        futures = [
            executor.submit(check_direct, endpoint, args.timeout, args.retries)
            for endpoint in endpoints
        ]
        results = [future.result() for future in futures]
    total_elapsed = time.perf_counter() - started

    print_results(results, use_color)
    print(f"总耗时: {total_elapsed:.2f}s")

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
