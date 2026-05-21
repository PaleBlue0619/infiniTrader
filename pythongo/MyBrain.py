import pandas as pd
from MyPosition import MyPosition
from MyOrder import MyOrder
from typing import Dict, List

class Event: # 基本动作 -> 开/平 * 多/空 * 手数 * * 最短/最长订单 * 最短/最长持仓 * 保证金率 * 止盈比例 * 止损比例
    def __init__(self):
        """
        开仓动作: direction + margin_rate + amount + multi + volume + vol + minOrderTimeStamp & maxOrderTimeStamp + minPosTimeStamp + maxPosTimeStamp
        平仓动作: direction + volume + vol + multi+ minOrderTimeStamp + maxOrderTimeStamp
        """
        self.direction: str = None    # long/short
        self.amount: float = None
        self.volume: int = None # 总数量
        self.vol: int = None    # 下单数量(总数量 = 下单数量 * 交易乘数)
        self.multi: int = None  # 交易乘数
        self.marginRate: float = None   # 保证金率
        self.minOrderTimestamp: pd.Timestamp = None # 最短订单时间
        self.maxOrderTimestamp: pd.Timestamp = None # 最长订单时间
        self.minPosTimestamp: pd.Timestamp = None   # 最短平仓时间(不得早于该时间平仓)
        self.maxPosTimestamp: pd.Timestamp = None   # 最长持仓时间(到达该时间必须强制平仓)
        self.upLimit: float = None  # 止盈比例
        self.downLimit: float = None    # 止损比例

    def openInit(self, direction: str, amount: float, volume: int, vol: int, multi: int, marginRate: float,
                 minOrderTimeStamp: pd.Timestamp, maxOrderTimeStamp: pd.Timestamp,
                 minPosTimestamp: pd.Timestamp = None, maxPosTimestamp: pd.Timestamp = None,
                 upLimit: float = None, downLimit: float = None):
        """开仓行为初始化"""
        self.direction = direction
        self.amount = amount
        self.volume = volume
        self.vol = vol
        self.multi = multi
        self.marginRate = marginRate
        self.minOrderTimestamp = minOrderTimeStamp
        self.maxOrderTimestamp = maxOrderTimeStamp
        self.minPosTimestamp = minPosTimestamp
        self.maxPosTimestamp = maxPosTimestamp
        self.upLimit = upLimit
        self.downLimit = downLimit

    def closeInit(self, direction: str, volume: int, vol: int, multi: int,
                  minOrderTimeStamp: pd.Timestamp, maxOrderTimeStamp: pd.Timestamp):
        """平仓行为初始化"""
        self.direction = direction
        self.volume = volume
        self.vol = vol
        self.multi = multi
        self.minOrderTimestamp = minOrderTimeStamp
        self.maxOrderTimestamp = maxOrderTimeStamp

class MyBrain(MyPosition, MyOrder):
    def __init__(self, ):
        super(MyBrain, self).__init__()
        self.stack: List[Event] = []

    # def addOpenEvent(self, data: pd.DataFrame):
    #     """从realTimeSignal.csv(from PyBackTest)中引入实时下单计划"""
    #     for
