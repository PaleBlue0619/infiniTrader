import os, json, json5
import pandas as pd
from copy import copy
from typing import List, Dict

class MyOrder:
    """自定义Order管理类 -> List这里并不代表顺序(因为Order并不遵循FIFO)"""
    def __init__(self) -> None:
        self.longOrder: Dict[str, List[Dict[str, any]]] = {}
        self.shortOrder: Dict[str, List[Dict[str, any]]] = {}

    def inputOrder(self, direction: str, savePath: str, fileName: str):
        """从Json中加载订单"""
        if not os.path.exists(rf"{savePath}\{fileName}"):
            return
        with open(rf"{savePath}\{fileName}", "r", encoding="utf-8") as f:
            orderDict: Dict[str, List[Dict[str, any]]] = json5.load(f)
        for symbol, posList in orderDict.items():  # 转换为pd.Timestamp
            for pos in posList:  # 类型转换
                pos["minOrderTime"] = pd.Timestamp(pos["minOrderTime"])
                pos["maxOrderTime"] = pd.Timestamp(pos["maxOrderTime"])
        for symbol, orderList in orderDict.items():
            self.setOrder(direction=direction, symbol=symbol, orderList=orderList)

    def getOrder(self, direction: str, symbol: str = None):
        """查询订单"""
        if not symbol:
            if direction == "long":
                return self.longOrder
            else:
                return self.shortOrder
        else:
            if direction == "long":
                if symbol in self.longOrder:    # 说明有这个合约的多单订单
                    return self.longOrder[symbol]
                return {}   # 说明有这个合约的空单订单
            else:
                if symbol in self.shortOrder:   # 说明有这个合约的空单订单
                    return self.shortOrder[symbol]
                return {}   # 说明没有这个合约的空单订单

    def setOrder(self, direction: str, symbol: str, orderList: List[Dict[str, any]]):
        """加载订单"""
        if direction == "long":
            self.longOrder[symbol] = orderList
        else:
            self.shortOrder[symbol] = orderList

    def openOrder(self, orderIdx: int, symbol: str, vol: int, price: float, direction: str,
                minOrderTime: pd.Timestamp, maxOrderTime: pd.Timestamp,
                staticHigh: float, staticLow: float):
        """开仓回调函数"""
        order = {"orderIdx": orderIdx,
                 "symbol": symbol,
                 "vol": vol,
                 "price": price,
                 "direction": direction,
                 "minOrderTime": minOrderTime,
                 "maxOrderTime": maxOrderTime,
                 "staticHigh": staticHigh,
                 "staticLow": staticLow
        }
        if direction == "long":  # 多单订单
            if symbol not in self.longOrder:
                self.longOrder = [order]
            else:
                self.longOrder.append(order)
        else:
            if symbol not in self.shortOrder:
                self.shortOrder = [order]
            else:
                self.shortOrder.append(order)

    def cancelOrder(self, symbol: str, direction: str, orderIdx: int = None):
        """取消某个合约订单/所有订单"""
        if direction == "long":
            if symbol in self.longOrder:
                if orderIdx:    # 有编号删除
                    idxList = [order["orderIdx"] for order in self.longOrder[symbol]]
                    if orderIdx in idxList:
                        del self.longOrder[symbol][idxList.index(orderIdx)]
                else:   # 删除该品种+该方向所有订单
                    del self.longOrder[symbol]
        else:
            if symbol in self.shortOrder:
                del self.shortOrder[symbol]
                if orderIdx:    # 有编号删除
                    idxList = [order["orderIdx"] for order in self.shortOrder[symbol]]
                    if orderIdx in idxList:
                        del self.shortOrder[symbol][idxList.index(orderIdx)]
                else: # 删除该品种+该方向所有订单
                    del self.shortOrder[symbol]

    def copy(self) -> "MyOrder":
        """浅拷贝自身"""
        return copy(self)

    def outputOrder(self, direction: str, savePath: str, fileName: str) -> None:
        """输出订单为Json5格式"""
        if direction == "long":
            orderDict = self.longOrder.copy()
        else:
            orderDict = self.shortOrder.copy()
        for symbol, posList in orderDict.items():
            for pos in posList:  # 类型转换
                pos["minOrderTime"] = pd.Timestamp(pos["minOrderTime"]).strftime("%Y.%m.%d %H:%M:%S")
                pos["maxOrderTime"] = pd.Timestamp(pos["maxOrderTime"]).strftime("%Y.%m.%d %H:%M:%S")
        with open(rf"{savePath}\{fileName}", "w", encoding="utf-8") as f:
            json5.dump(orderDict, f)
