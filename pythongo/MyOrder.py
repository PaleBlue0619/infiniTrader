import os, json, json5
import pandas as pd
from copy import copy
from typing import List, Dict

class MyOrder:
    """自定义Order管理类 -> List这里并不代表顺序(因为Order并不遵循FIFO)"""
    def __init__(self) -> None:
        self.orderDict: Dict[int, Dict[str, any]] = {}

    def inputOrder(self, savePath: str, fileName: str):
        """从Json中加载订单"""
        if not os.path.exists(rf"{savePath}\{fileName}"):
            return
        with open(rf"{savePath}\{fileName}", "r", encoding="utf-8") as f:
            orderDict: Dict[str, List[Dict[str, any]]] = json5.load(f)
        for symbol, posList in orderDict.items():  # 转换为pd.Timestamp
            for pos in posList:  # 类型转换
                pos["minOrderTime"] = pd.Timestamp(pos["minOrderTime"]) if pos["minOrderTime"] else None
                pos["maxOrderTime"] = pd.Timestamp(pos["maxOrderTime"]) if pos["maxOrderTime"] else None
                pos["minPosTime"] = pd.Timestamp(pos["minPosTime"]) if pos["minPosTime"] else None
                pos["maxPosTime"] = pd.Timestamp(pos["maxPosTime"]) if pos["maxPosTime"] else None
        self.setOrder(orderDict=orderDict)

    def getOrder(self, idx: int = None) -> Dict[int, Dict[str, any]]:
        """查询订单"""
        if not idx:
            return self.orderDict
        return self.orderDict.get(idx, {})

    def setOrder(self, orderDict: Dict[int, Dict[str, any]]):
        """加载订单"""
        self.orderDict = orderDict

    def openOrder(self, orderIdx: int, state: str, symbol: str, vol: int, price: float, direction: str,
                minOrderTime: pd.Timestamp = None, maxOrderTime: pd.Timestamp = None,
                minPosTime: pd.Timestamp = None, maxPosTime: pd.Timestamp = None,
                upLimit: float = None, downLimit: float = None):
        """订单回调函数"""
        order = {"state": state,
                 "symbol": symbol,
                 "vol": vol,
                 "price": price,
                 "direction": direction,
                 "minOrderTime": minOrderTime,
                 "maxOrderTime": maxOrderTime,
                 "minPosTime": minPosTime,
                 "maxPosTime": maxPosTime,
                 "upLimit": upLimit,
                 "downLimit": downLimit
        }
        self.orderDict[orderIdx] = order

    def cancelOrder(self, orderIdx: int):
        if orderIdx in self.orderDict:
            del self.orderDict[orderIdx]

    def copy(self) -> "MyOrder":
        """浅拷贝自身"""
        return copy(self)

    def outputOrder(self, savePath: str, fileName: str) -> None:
        """输出订单为Json5格式"""
        orderDict = self.orderDict.copy()
        for symbol, posList in orderDict.items():
            for pos in posList:  # 类型转换
                pos["minOrderTime"] = pd.Timestamp(pos["minOrderTime"]).strftime("%Y.%m.%d %H:%M:%S") if pos["minOrderTime"] else None
                pos["maxOrderTime"] = pd.Timestamp(pos["maxOrderTime"]).strftime("%Y.%m.%d %H:%M:%S") if pos["maxOrderTime"] else None
                pos["minPosTime"] = pd.Timestamp(pos["minPosTime"]).strftime("%Y.%m.%d %H:%M:%S") if pos["minPosTime"] else None
                pos["maxPosTime"] = pd.Timestamp(pos["maxPosTime"]).strftime("%Y.%m.%d %H:%M:%S") if pos["maxPosTime"] else None
        with open(rf"{savePath}\{fileName}", "w", encoding="utf-8") as f:
            json5.dump(orderDict, f)
