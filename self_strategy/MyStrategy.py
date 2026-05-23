import os, sys, json, json5
import dolphindb as ddb
import pandas as pd
from datetime import datetime
from copy import copy
from typing import Literal, Dict, List
from pythongo.MyPosition import MyPosition
from pythongo.MyOrder import MyOrder
from pythongo.MyBrain import MyBrain
from pythongo.MyUtils import createInfoTable, createTradeTable, createOrderTable, \
    product_formatter, contract_formatter, process_marginRate
# 从 base 库中导入定义参数和状态映射模型必须的三个方法
from pythongo.base import BaseParams, BaseState, Field, BaseStrategy
from pythongo.classdef import KLineData, OrderData, TickData, TradeData, Position
from pythongo.core import KLineStyleType, MarketCenter
from pythongo.utils import KLineGenerator, KLineContainer

"""
交易系统所有功能:
x: 基本信息(交易时间 + 保证金)写入DolphinDB共享流表 [待测试]
0. 盘前录入开仓的期货合约(止盈止损最长持仓时间) + 昨日仓位状态 + 昨日订单状态 [待测试]
1. 开盘挂单开仓 -> on_tick 
2. on_order中将订单记录写入DolphinDB共享流表 + 调用MyOrder回调更新内存状态 [待测试]
3. 实时监控持仓 -> on_bar 中平仓
4. on_trade中将成交记录写入DolphinDB共享流表 + 调用MyPosition回调更新内存状态 [待测试]
5. 离收盘前半小时撤单 + 禁止下单
6. 策略暂停时/收盘时 -> 自动保存所有订单状态 + 仓位状态 [待测试]
y: 后续考虑将所有流数据表开启持久化 or 直接用dimensionTable进行代替
z: TWAP/VWAP进行下单 -> 由于个人交易下单量较小+持仓周期日级别以上, ask1/bid1已经能满足盘口, 所以该需求的优先级不高
"""


class Params(BaseParams):
    """参数映射模型 -> 从无限易窗口中传入的参数定义的值
    Field: 自定义元数据->添加至参数映射模型的字段中
    default: 定义这个参数的默认值
    title: 定义这个参数的中文明 -> 会在PythonGO中显示
    """
    # 这里说白了就是方便单品种时序CTA固定策略, 然后在不更换模板的情况下换品种执行, 如果是多品种CTA策略可以跳过这一步

class State(BaseState):
    """
    状态映射模型 -> 在无限易状态栏查看报单编号的值
    """
    order_id: int | None = Field(default=None, title="报单编号")

class MyStrategy(BaseStrategy):
    """实盘策略主体
    在编写回调函数时, 回调函数应当按照以下顺序定义, 用不到的回调函数允许不定义
    """

    def __init__(self) -> None:
        super().__init__()
        with open(r"E:\Quant\QuantTrader\infiniTrader\cons\config.json5", "r", encoding="utf-8") as f:
            self.config = json5.load(f)
        self.session = ddb.session(host=self.config["session"]["host"],
                                   port=self.config["session"]["port"],
                                   userid=self.config["session"]["userid"],
                                   password=self.config["session"]["password"])
        self.pathStr: str = self.config["record"]["pathStr"]  # 储存持仓信息&订单信息的路径
        self.longPosFile: str = self.config["record"]["longPos"]
        self.shortPosFile: str = self.config["record"]["shortPos"]
        self.longOrderFile: str = self.config["record"]["longOrder"]
        self.shortOrderFile: str = self.config["record"]["shortOrder"]
        self.signalFile: str = self.config["signalFile"]
        self.infoTable: str = self.config["record"]["infoTable"]
        createInfoTable(session=self.session, tableName=self.config["record"]["infoTable"],
                        dropTB=self.config["record"]["dropTB"])
        createTradeTable(session=self.session, tableName=self.config["record"]["tradeTable"],
                         dropTB=self.config["record"]["dropTB"])
        createOrderTable(session=self.session, tableName=self.config["record"]["orderTable"],
                         dropTB=self.config["record"]["dropTB"])
        # 由于不做股指+国债期货(即CFX交易所的品种), 所以这里直接日盘取连续的就好, 回调中统一处理1015+1130+1330这三个断点
        self.infoDict = {'AP': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'CF': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'CJ': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'CY': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'FG': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'IC': {'exchange': 'CFFEX', 'multi': 200, 'format': 4, 'nightTime': False, 'dayTime': [930, 1500]},
                         'IF': {'exchange': 'CFFEX', 'multi': 300, 'format': 4, 'nightTime': False, 'dayTime': [930, 1500]},
                         'IH': {'exchange': 'CFFEX', 'multi': 300, 'format': 4, 'nightTime': False, 'dayTime': [930, 1500]},
                         'IM': {'exchange': 'CFFEX', 'multi': 200, 'format': 4, 'nightTime': False, 'dayTime': [930, 1500]},
                         'JR': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'MA': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'OI': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'PF': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'PK': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'PL': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'PM': {'exchange': 'CZCE', 'multi': 50, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'PR': {'exchange': 'CZCE', 'multi': 15, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'PX': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'RI': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'RM': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'RS': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'SA': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'SF': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'SH': {'exchange': 'CZCE', 'multi': 30, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'SM': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'SR': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'T': {'exchange': 'CFFEX', 'multi': 10000, 'format': 4, 'nightTime': False, 'dayTime': [930, 150]},
                         'TA': {'exchange': 'CZCE', 'multi': 5, 'format': 3, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'TF': {'exchange': 'CFFEX', 'multi': 10000, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'TL': {'exchange': 'CFFEX', 'multi': 10000, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'TS': {'exchange': 'CFFEX', 'multi': 20000, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'UR': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'WH': {'exchange': 'CZCE', 'multi': 20, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'ZC': {'exchange': 'CZCE', 'multi': 100, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
                         'a': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'ad': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'ag': {'exchange': 'SHFE', 'multi': 15, 'format': 4, 'nightTime': [2100, 230], 'dayTime': [900, 1500]},
                         'al': {'exchange': 'SHFE', 'multi': 5, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'ao': {'exchange': 'SHFE', 'multi': 20, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'au': {'exchange': 'SHFE', 'multi': 1000, 'format': 4, 'nightTime': [2100, 230], 'dayTime': [900, 1500]},
                         'b': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'bb': {'exchange': 'DCE', 'multi': 500, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'bc': {'exchange': 'INE', 'multi': 5, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'br': {'exchange': 'SHFE', 'multi': 5, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'bu': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'bz': {'exchange': 'DCE', 'multi': 30, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'c': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'cs': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'cu': {'exchange': 'SHFE', 'multi': 5, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'eb': {'exchange': 'DCE', 'multi': 5, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'ec': {'exchange': 'INE', 'multi': 50, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'eg': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'fb': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'fu': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'hc': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'i': {'exchange': 'DCE', 'multi': 100, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'j': {'exchange': 'DCE', 'multi': 100, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'jd': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'jm': {'exchange': 'DCE', 'multi': 60, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'l': {'exchange': 'DCE', 'multi': 5, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'lc': {'exchange': 'GFFEX', 'multi': 1, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'lg': {'exchange': 'DCE', 'multi': 90, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'lh': {'exchange': 'DCE', 'multi': 16, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'lu': {'exchange': 'INE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'm': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'ni': {'exchange': 'SHFE', 'multi': 1, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'nr': {'exchange': 'INE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'op': {'exchange': 'SHFE', 'multi': 40, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'p': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'pb': {'exchange': 'SHFE', 'multi': 5, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'pd': {'exchange': 'GFEX', 'multi': 1000, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'pg': {'exchange': 'DCE', 'multi': 20, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'pp': {'exchange': 'DCE', 'multi': 5, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'ps': {'exchange': 'GFEX', 'multi': 3, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'pt': {'exchange': 'GFEX', 'multi': 1000, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'rb': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'rr': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'ru': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'sc': {'exchange': 'INE', 'multi': 1000, 'format': 4, 'nightTime': [2100, 230], 'dayTime': [900, 1500]},
                         'si': {'exchange': 'GFEX', 'multi': 5, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'sn': {'exchange': 'SHFE', 'multi': 1, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'sp': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'ss': {'exchange': 'SHFE', 'multi': 5, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]},
                         'v': {'exchange': 'DCE', 'multi': 5, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'wr': {'exchange': 'SHFE', 'multi': 10, 'format': 4, 'nightTime': False, 'dayTime': [900, 1500]},
                         'y': {'exchange': 'DCE', 'multi': 10, 'format': 4, 'nightTime': [2100, 2300], 'dayTime': [900, 1500]},
                         'zn': {'exchange': 'SHFE', 'multi': 5, 'format': 4, 'nightTime': [2100, 100], 'dayTime': [900, 1500]}
                         }
        self.myBrain: MyBrain = MyBrain()   # 策略大脑 -> 管理Position + Order -> on_start中初始化
        # self.myPosition: MyPosition = MyPosition()  # 上一个交易日收盘时的持仓状态 -> on_start中初始化
        # self.myOrder: MyOrder = MyOrder()  # 上一个交易日收盘时的订单状态 -> on_start中初始化
        # 禁止下单+监控的品种
        self.deleteProduct: List[str] = self.config["deleteProduct"]
        # 所有需要被监视的合约+交易所(为了节省轮寻时间 -> 只对需要交易的品种进行实时监控)
        self.monitorProduct: List[str] = []     # 可能有重复值
        self.monitorContract: List[str] = []    # 需要监视的合约
        self.monitorExchange: List[str] = []    # 对应的交易所代码
        self.oriPosDict: Dict[str, Dict[str, Dict[str, Position]]] = {}  # 获取当前账号所有持仓
        self.market_center: MarketCenter = MarketCenter()  # 行情获取中心
        self.kline_generators: Dict[str, KLineGenerator] = {}  # 所有品种的1分钟K线合成器
        self.kline_containers: Dict[str, KLineContainer] = {}  # 所有品种的1分钟K线储存器

    def get_info(self, monitorProduct: List[str] = None, deleteProduct: List[str] = None) -> pd.DataFrame:
        """获取品种基本信息
        TODO: 需要思考备用数据channel -> 万一这个交易星球网崩了/缺数据怎么办 -> 转tushare futSettle补全数据
        """
        # 处理外部输入的marginRate数据 + 市场合约数据
        infoDF = process_marginRate(filePath=rf"{self.pathStr}\{self.config['record']['marginFile']}", infoDict=self.infoDict,
                                    savePath=self.pathStr, fileName="marginInfo.csv")
        # 交易星球数据不如infiniTrader自身给的主力合约质量高
        mainContDF = pd.read_excel(rf"{self.pathStr}\{self.config['record']['infiniFile']}",index_col=None, header=0)
        mainContDict = dict(zip(mainContDF["品种"], mainContDF["合约名称"]))
        infoDF = infoDF[infoDF["isMainContract"] == 1].reset_index(drop=True)
        infoDF["product"] = infoDF["contract"].apply(lambda x: "".join([str(i) for i in x if str(i).isalpha()]))
        infoDF["contract"] = infoDF["product"].map(mainContDict)    # 更新主力合约 -> 交易星球的大写字母合约real_html解析会吞掉前面的年份, 但年份无法确定, 保险起见全部用无限易的主力合约
        if monitorProduct:
            infoDF = infoDF[infoDF["product"].isin(monitorProduct)].reset_index(drop=True)
        if deleteProduct:
            infoDF = infoDF[~infoDF["product"].isin(deleteProduct)].reset_index(drop=True)
        infoDF["exchange"] = infoDF["product"].apply(lambda x: self.infoDict[x]["exchange"])
        infoDF["multi"] = infoDF["product"].apply(lambda x: self.infoDict[x]["multi"])
        infoDF["hasNightTrade"] = infoDF["product"].apply(lambda x: True if self.infoDict[x]["nightTime"] else False)
        currentTime = pd.Timestamp.now()
        currentMinute = int(currentTime.hour * 100 + currentTime.minute)
        """
        让我们来仔细想一下如何实现不同时间段启动策略都能看到正确的时间, 因为
        [0000, 0230] -> 这时候启动策略一定是上一个交易日的延续的夜盘 -> nightOpen: 昨天, nightClose: 今天, dayOpen: 今天, dayClose: 今天
        [0231, 1500] -> 这时候启动策略一定是今天日盘 -> nightOpen: 今天, nightClose: 今天/明天, dayOpen: 今天, dayClose: 今天 (因为我不做国债期货所以取1500为分界点)
        [1501, 2359] -> 这时候启动策略一定是今天夜盘 -> nightOpen: 今天, nightClose: 今天/明天, dayOpen: 明天, dayClose: 明天
        """
        lastDateStr = pd.Timestamp(pd.Timestamp.now().date() - pd.offsets.BusinessDay(1)).strftime("%Y-%m-%d")  # 2026-05-20
        currentDateStr = pd.Timestamp.now().date().strftime("%Y-%m-%d")   # 2026-05-21
        nextDateStr = pd.Timestamp(pd.Timestamp.now().date() + pd.offsets.BusinessDay(1)).strftime("%Y-%m-%d")  # 2026-05-22
        infoDF["nightOpenTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["nightTime"][0]).zfill(4) if self.infoDict[x]["nightTime"] else None)
        infoDF["nightCloseTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["nightTime"][1]).zfill(4) if self.infoDict[x]["nightTime"] else None)
        infoDF["dayOpenTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["dayTime"][0]).zfill(4) if self.infoDict[x]["dayTime"] else None)
        infoDF["dayCloseTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["dayTime"][1]).zfill(4) if self.infoDict[x]["dayTime"] else None)
        if currentMinute <= 230:    # 上一个交易日延续的夜盘
            infoDF["nightOpenTime"] = infoDF["nightOpenTime"].apply(lambda x:pd.Timestamp(lastDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["nightCloseTime"] = infoDF["nightCloseTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["dayOpenTime"] = infoDF["dayOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["dayCloseTime"] = infoDF["dayCloseTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        elif 231 <= currentMinute <= 1500:  # 今天日盘
            infoDF["nightOpenTime"] = infoDF["nightOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["nightCloseTime"] = infoDF["nightCloseTime"].apply(lambda x:pd.Timestamp({"2300": currentDateStr}.get(x, nextDateStr)+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["dayOpenTime"] = infoDF["dayOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["dayCloseTime"] = infoDF["dayCloseTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        else:   # 今天夜盘
            infoDF["nightOpenTime"] = infoDF["nightOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["nightCloseTime"] = infoDF["nightCloseTime"].apply(lambda x:pd.Timestamp({"2300": currentDateStr}.get(x, nextDateStr)+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["dayOpenTime"] = infoDF["dayOpenTime"].apply(lambda x:pd.Timestamp(nextDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
            infoDF["dayCloseTime"] = infoDF["dayCloseTime"].apply(lambda x:pd.Timestamp(nextDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["openTime"] = infoDF.apply(lambda row: row["nightOpenTime"] if pd.notnull(row["nightOpenTime"]) else row["dayOpenTime"], axis=1)
        infoDF["closeTime"] = infoDF["dayCloseTime"]    # 必定有日盘 -> 收盘即为日盘时间
        infoDF = infoDF[["product","exchange","contract","multi","longMarginRate","shortMarginRate",
                         "hasNightTrade","openTime","closeTime",
                         "nightOpenTime","nightCloseTime","dayOpenTime","dayCloseTime",
                         "isMainContract"]]   # 调整列顺序
        return infoDF

    def on_start(self) -> None:
        """策略启动的回调函数"""
        # 初始化K线合成器
        super().on_start()

        # 初始化pathStr
        if not os.path.exists(path=self.pathStr):
            os.mkdir(self.pathStr)

        # 获取当前所有持仓
        self.oriPosDict = self.get_all_position()  # TODO: 调用接口获取当前账户所有持仓
        self.output(self.oriPosDict)

        # 本地加载Position + Order -> MyBrain初始化
        self.myBrain.init(pathStr=self.pathStr, longPosFile=self.longPosFile, shortPosFile=self.shortPosFile,
                          longOrderFile=self.longOrderFile, shortOrderFile=self.shortOrderFile)
        # self.myPosition.inputPos(direction="long", savePath=self.pathStr, fileName=self.longPosFile)
        # self.myPosition.inputPos(direction="short", savePath=self.pathStr, fileName=self.shortPosFile)
        # self.myOrder.inputOrder(direction="long", savePath=self.pathStr, fileName=self.longOrderFile)
        # self.myOrder.inputOrder(direction="short", savePath=self.pathStr, fileName=self.shortOrderFile)
        currentContract = list(set(list(self.myBrain.Position.longPos.keys())+list(self.myBrain.Position.shortPos.keys())))     # 当前持仓合约
        currentProduct = list(["".join([j for j in i if str(j).isalpha()]) for i in currentContract])   # 当前持仓品种

        # 向基本信息表中添加查询后的合约信息
        self.deleteProduct = product_formatter(productList=self.deleteProduct, infoDict=self.infoDict)
        contractInfo = self.get_info(monitorProduct=None, deleteProduct=self.deleteProduct)
        self.session.upload({"contractInfo": contractInfo})
        self.session.run(f"""objByName("{self.infoTable}", true).append!(contractInfo)""")
        self.output("""[INFO] 合约信息加载完毕""")

        # 删除不需要的infoDict
        for product in self.deleteProduct:
            if product in self.infoDict:
                del self.infoDict[product]

        # 本地加载开仓信号 + 规范品种&合约名称 -> 没有则跳过
        openSignal = pd.read_csv(self.signalFile, index_col=None, header=0).rename(columns={"contract": "symbol"})
        openSignal["product"] = product_formatter(productList=list(openSignal["product"]), infoDict=self.infoDict)
        openSignal["symbol"] = contract_formatter(contractList=list(openSignal["symbol"]), infoDict=self.infoDict)
        infoDF = self.session.run(f"""select * from objByName("{self.infoTable}", true)""")   # DolphinDB共享流表(品种信息)
        openSignal = openSignal[~openSignal["product"].isin(self.deleteProduct)].reset_index(drop=True)  # 剔除黑名单品种
        self.myBrain.addOpenEvents(data=openSignal, info=infoDF)
        self.output("""[INFO] 本地加载信号完毕""")

        # 更新主力合约至infoDict
        mainContractInfo = contractInfo[contractInfo["isMainContract"] == 1].reset_index(drop=True)  # 这里isMainContract都是1, 这样写为了方便后续拓展
        mainContractDict = dict(zip(mainContractInfo["product"], mainContractInfo["contract"]))
        for product, info in self.infoDict.items():
            self.infoDict[product]["mainContract"] = mainContractDict[product]

        # 决定本次运行所有需要监视的合约 + 交易所
        self.monitorProduct = product_formatter(productList=self.config["monitorProduct"] + currentProduct, infoDict=self.infoDict)
        self.monitorContract = contract_formatter(contractList=currentContract, infoDict=self.infoDict)
        self.monitorExchange = [self.infoDict[product]["exchange"] for product in self.monitorProduct]
        self.output(f"[INFO] 监控合约: {self.monitorContract}")

        # 每个合约获取最近1根1分钟K线
        for exchange, contract in zip(self.monitorExchange, self.monitorContract):
            kline_generator = KLineGenerator(
                # real_time_callback=None,
                callback=self.on_bar,  # bar回调函数
                exchange=exchange,
                instrument_id=contract,
                style="M1"
            )  # 代表一分钟K线 -> 详见https://infinitrader.quantdo.com.cn/pythongo_v2/modules/pythongo_core#klinestyle
            kline_container = KLineContainer(
                exchange=exchange,
                instrument_id=contract,
                style="M1"
            )
            kline_generator.push_history_data()
            self.kline_generators[contract] = kline_generator
            self.kline_containers[contract] = kline_container

        # 每个合约订阅行情
        for exchange, contract in zip(self.monitorExchange, self.monitorContract):
            self.sub_market_data(
                exchange=exchange,
                instrument_id=contract
            )

    def on_tick(self, tick: TickData) -> None:
        """tick回调函数 -> 用于用户级别开平仓"""
        self.kline_generators[tick.instrument_id].tick_to_kline(tick)
        self.output(tick)
        self.output(self.kline_containers[tick.instrument_id].get(exchange=tick.exchange,
                                                                  instrument_id=tick.instrument_id,
                                                                  style="1M"))  # 如果为空输出为[]

    def on_order(self, order: OrderData) -> None:
        """
        订单回调函数 -> 用于记录订单信息
        实时写入DolphinDB流表
        """
        super().on_order(order)
        # DolphinDB记录订单信息
        tableName = self.config["record"]["orderTable"]
        rowData = [order.exchange,
                   order.instrument_id,
                   order.price,
                   order.order_id,
                   order.order_sys_id,
                   int(order.order_price_type),
                   int(order.direction),  # 买卖方向
                   int(order.offset),  # 开平仓标志
                   pd.Timestamp(order.cancel_time),
                   pd.Timestamp(order.order_time),
                   pd.Timestamp.now()
                   ]
        self.session.run(f"tableInsert{ {tableName} }", rowData)

    def on_trade(self, trade: TradeData, log: bool = False) -> None:
        """
        成交回调函数 -> 用于记录成交信息
        实时写入DolphinDB流表
        """
        super().on_trade(trade, log)
        # 从报单编号列表中移除对应的报单编号
        if trade.order_id in self.order_id:
            self.order_id.remove(trade.order_id)
        # DolphinDB记录成交信息
        tableName = self.config["record"]["tradeTime"]
        rowData = [
            trade.exchange,
            trade.instrument_id,
            trade.trade_id,
            trade.order_id,
            trade.order_sys_id,
            pd.Timestamp(trade.trade_time),
            int(trade.direction),
            int(trade.offset),
            trade.price,
            trade.volume,
            pd.Timestamp.now()
        ]
        # DolphinDB记录成交信息
        self.session.run(f"tableInsert{ {tableName} }", rowData)

    def on_order_cancel(self, order: OrderData) -> None:
        """撤单推送回调"""
        super().on_order_cancel(order)
        # 从报单编号中移除对应的报单编号
        if order.order_id in self.order_id:
            self.order_id.remove(order.order_id)

    def on_stop(self) -> None:
        super().on_stop()

        # 每个合约取消订阅行情
        for exchange, contract in zip(self.monitorExchange, self.monitorContract):
            self.unsub_market_data(
                exchange=exchange,
                instrument_id=contract
            )
        # 保存订单信息 & 保存持仓信息
        self.myBrain.save(pathStr=self.pathStr, longPosFile=self.longPosFile, shortPosFile=self.shortPosFile,
                          longOrderFile=self.longOrderFile, shortOrderFile=self.shortOrderFile)
        # self.myOrder.outputOrder(direction="long", savePath=self.pathStr, fileName=self.longOrderFile)
        # self.myOrder.outputOrder(direction="short", savePath=self.pathStr, fileName=self.shortOrderFile)
        # self.myPosition.outputPos(direction="long", savePath=self.pathStr, fileName=self.longPosFile)
        # self.myPosition.outputPos(direction="short", savePath=self.pathStr, fileName=self.shortPosFile)
        self.output("[INFO] Order 状态信息Json5保存完毕")
        self.output("[INFO] Position 状态信息Json5保存完毕")

    # 其他回调函数
    def on_bar(self, kline: KLineData) -> None:
        """接受K线回调"""
        return

    def on_bar_realTime(self, kline: KLineData) -> None:
        """接受实时K线回调"""
        return
