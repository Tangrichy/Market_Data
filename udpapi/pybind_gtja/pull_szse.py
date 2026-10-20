#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
深交所行情拉取脚本。

默认连接深交所行情前置，订阅全部合约，持续打印并在 CSV 中保存多档盘口。

用法：
    python pull_szse.py
    python pull_szse.py --symbols 000001,002114 --levels 10 --output szse_ticks.csv
    python pull_szse.py --multi --duration 60
"""
import sys
import pull_data

# 深交所行情前置地址
SZSE_FRONT = "tcp://183.63.193.58:42116"

if __name__ == "__main__":
    # 如果用户没有显式指定 --front，则默认使用深交所前置
    if "--front" not in sys.argv:
        sys.argv.extend(["--front", SZSE_FRONT])
    pull_data.main()
