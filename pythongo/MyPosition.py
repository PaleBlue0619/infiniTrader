import os, json, json5
import pandas as pd
from copy import copy
from typing import List, Dict

class MyPosition:
    """自定义FIFO仓位管理类"""
    def __init__(self, ):
        self.longPos: Dict[str, List[Dict[str, any]]] = {}
        self.shortPos: Dict[str, List[Dict[str, any]]] = {}

    def inputPos(self, direction: str, savePath: str, fileName: str) -> None:
        """从Json5中初始化仓位"""
        if not os.path.exists(rf"{savePath}\{fileName}"):
            return
        with open(rf"{savePath}\{fileName}", "r", encoding="utf-8") as f:
            posDict: Dict[str, List[Dict[str, any]]] = json5.load(f)
        for symbol, posList in posDict.items():  # 转换为pd.Timestamp
            for pos in posList:  # 类型转换
                pos["minPosTime"] = pd.Timestamp(pos["minPosTime"])
                pos["maxPosTime"] = pd.Timestamp(pos["maxPosTime"])
        for symbol, posList in posDict.items():
            self.setPos(direction=direction, symbol=symbol, posList=posList)

    def getPos(self, direction: str, symbol: str = None):
        """获取当前仓位"""
        if not symbol:
            if direction == "long":
                return self.longPos
            else:
                return self.shortPos
        else:
            if direction == "long":
                if symbol in self.longPos:  # 说明有这个多仓持仓
                    return self.longPos[symbol]
                return {}
            else:
                if symbol in self.shortPos: # 说明有这个空仓持仓
                    return self.shortPos[symbol]
                return {}

    def setPos(self, direction: str, symbol: str, posList: List[Dict[str, any]]):
        """加载单个仓位 -> 其中日期需要调整"""
        # 设置/更新仓位
        if direction == "long":
            self.longPos[symbol] = posList
            # 类型转换
            for pos in self.longPos[symbol]:
                pos["minPosTime"] = pd.Timestamp(pos["minPosTime"])
                pos["maxPosTime"] = pd.Timestamp(pos["maxPosTime"])
        else:
            self.shortPos[symbol] = posList
            # 类型转换
            for pos in self.shortPos[symbol]:
                pos["minPosTime"] = pd.Timestamp(pos["minPosTime"])
                pos["maxPosTime"] = pd.Timestamp(pos["maxPosTime"])

    # 开仓/加仓回调函数
    def openPos(self, direction: str, symbol: str, price: float, vol: int, minPosTime: pd.Timestamp, maxPosTime: pd.Timestamp,
                staticHigh: float, staticLow: float) -> None:
        pos = {"price": price, "vol": vol, "minPosTime": minPosTime, "maxPosTime": maxPosTime, "staticHigh": staticHigh, "staticLow": staticLow}
        if direction == "long":
            if symbol not in self.longPos:
                self.longPos[symbol] = [pos]
            else:
                self.longPos[symbol].append(pos)
        else:
            if symbol not in self.shortPos:
                self.shortPos[symbol] = [pos]
            else:
                self.shortPos[symbol].append(pos)

    def delPos(self, direction: str, symbol: str, endIdx: int = None) -> None:
        """删除仓位函数: direction: 方向; symbol: 合约名称; endIdx: 下标位置 -> 不包含下标"""
        if direction == "long":
            if symbol in self.longPos:
                if not endIdx:  # 不指定删除截至的下标位置
                    del self.longPos[symbol]
                else:
                    del self.longPos[symbol][:endIdx]
        else:
            if symbol in self.shortPos:
                if not endIdx:  # 不指定删除截至的下标位置
                    del self.shortPos[symbol]
                else:
                    del self.shortPos[symbol][:endIdx]

    def closePos(self, direction: str, symbol: str, vol: int) -> None:
        """平仓 & 部分平仓函数"""
        if direction == "long":
            if symbol in self.longPos:
                volList: List[int] = [pos["vol"] for pos in self.longPos[symbol]]
                totalVol: int = sum(volList)    # 统计当前总持仓量
                if vol >= totalVol:   # 说明全部平仓
                    self.delPos(direction=direction, symbol=symbol, endIdx=None)
                else:
                    for v in volList:
                        if v > vol:   # 说明已经平到了指定的仓位
                            self.longPos[symbol][0]["vol"] -= vol
                            break
                        else:   # v<=vol -> 还需要继续往下平
                            self.delPos(direction=direction, symbol=symbol, endIdx=1)    # 平掉第1-1=0个(也就是最前面)的仓位
                            vol -= v
        else:
            if symbol in self.shortPos:
                volList: List[int] = [pos["vol"] for pos in self.shortPos[symbol]]
                totalVol: int = sum(volList)    # 统计当前总持仓量
                if vol >= totalVol:   # 说明全部平仓
                    self.delPos(direction=direction, symbol=symbol, endIdx=None)
                else:
                    for v in volList:
                        if v > vol:   # 说明已经平到了指定的仓位
                            self.shortPos[symbol][0]["vol"] -= vol
                            break
                        else:   # v<=vol -> 还需要继续往下平
                            self.delPos(direction=direction, symbol=symbol, endIdx=1)
                            vol -= vol

    def copy(self) -> "MyPosition":
        """浅拷贝自身"""
        return copy(self)

    # 输出仓位为json5
    def outputPos(self, direction: str, savePath: str, fileName: str) -> None:
        if direction == "long":
            posDict = self.longPos.copy()
        else:
            posDict = self.shortPos.copy()
        for symbol, posList in posDict.items():
            for pos in posList:  # 类型转换
                pos["minPosTime"] = pd.Timestamp(pos["minPosTime"]).strftime("%Y.%m.%d %H:%M:%S")
                pos["maxPosTime"] = pd.Timestamp(pos["maxPosTime"]).strftime("%Y.%m.%d %H:%M:%S")
        with open(rf"{savePath}\{fileName}", "w", encoding="utf-8") as f:
            json5.dump(posDict, f)
