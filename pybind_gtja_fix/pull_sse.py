#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
上交所行情拉取脚本。

默认连接上交所行情前置，订阅全部合约，持续打印并在 CSV 中保存多档盘口。

用法：
    python pull_sse.py
    python pull_sse.py --symbols 600000,688027 --levels 10 --output sse_ticks.csv
    python pull_sse.py --multi --duration 60
"""
import sys
import pull_data

# 上交所行情前置地址
SSE_FRONT = "tcp://183.193.54.200:21002"  #"tcp://114.94.154.60:21002"

if __name__ == "__main__":
    # 如果用户没有显式指定 --front，则默认使用上交所前置
    if "--front" not in sys.argv:
        sys.argv.extend(["--front", SSE_FRONT])
    pull_data.main()
