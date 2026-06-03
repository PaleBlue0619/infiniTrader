import os, sys, json, json5
import dolphindb as ddb
import pandas as pd
from datetime import datetime
from copy import copy
from typing import Literal, Dict, List
from pythongo.MyPosition import MyPosition
from pythongo.MyOrder import MyOrder
from pythongo.Event import Event, OrderOpenEvent, OrderCloseEvent
from pythongo.MyUtils import createInfoTable, createTradeTable, createOrderTable, \
    product_formatter, contract_formatter, process_marginRate, get_info, addHistEvents, addOpenEvents
# 从 base 库中导入定义参数和状态映射模型必须的三个方法
from pythongo.base import BaseParams, BaseState, Field, BaseStrategy
from pythongo.classdef import KLineData, OrderData, TickData, TradeData, Position
from pythongo.core import KLineStyleType, MarketCenter
from pythongo.utils import KLineGenerator, KLineContainer

"""
交易系统所有功能:
0: 盘前维护基本信息(交易时间 + 保证金)写入DolphinDB共享流表 [√]
0. 盘前录入开仓的期货合约(止盈止损最长持仓时间) + 昨日仓位状态 + 昨日订单状态 [待测试]
1. 开盘挂单开仓 -> on_bar 中挂单 [待测试] 
2. on_order中将订单记录写入DolphinDB共享流表 + 调用MyOrder回调更新内存状态 [待测试]
3. 实时监控持仓 -> on_bar 中平仓 [待测试]
4. on_trade中将成交记录写入DolphinDB共享流表 + 调用MyPosition回调更新内存状态 [待测试]
5. 离收盘前半小时撤单 + 禁止下单 [待实现]
6. 策略暂停时/收盘时 -> 自动保存所有订单状态 + 仓位状态 [待测试]
x: [!!] 挂单未成交场景会冻结保证金 -> 建议通过短信提醒人工干预或撤单并在on_cancel中实现撤单逻辑
y: 后续考虑将所有流数据表开启持久化 or 直接用dimensionTable进行代替
z: TWAP/VWAP下单算法 -> 由于个人交易下单量较小+持仓周期日级别以上, ask1/bid1已经能满足盘口, 所以该需求的优先级不高
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
        # 基本配置类
        with open(r"E:\Quant\QuantTrader\infiniTrader\cons\config.json5", "r", encoding="utf-8") as f:
            self.config = json5.load(f)
        self.lastMinute: int = int(pd.Timestamp.now().minute)   # 上一个时间戳 -> 用于onBar判断
        self.eventIdx: int = 0  # 全局订单编号
        self.eventWait: Dict[int, Event] = {}   # 待执行的event, int为eventId(MyStrategy维护)
        self.eventDoing: Dict[int, Event] = {}  # 正在执行的Event, int为orderId(柜台维护)
        self.myPosition: MyPosition = MyPosition()  # JUST FOR RECORD
        self.myOrder: MyOrder = MyOrder()   # JUST FOR RECORD
        self.session = ddb.session(host=self.config["session"]["host"],
                                   port=self.config["session"]["port"],
                                   userid=self.config["session"]["userid"],
                                   password=self.config["session"]["password"])

        # 事件记录类
        self.pathStr: str = self.config["record"]["pathStr"]  # 储存持仓信息&订单信息的路径
        self.longPosFile: str = self.config["record"]["longPosFile"]
        self.shortPosFile: str = self.config["record"]["shortPosFile"]
        self.orderFile: str = self.config["record"]["orderFile"]
        self.signalFile: str = self.config["signalFile"]
        self.infoTable: str = self.config["record"]["infoTable"]
        createInfoTable(session=self.session, tableName=self.config["record"]["infoTable"],
                        dropTB=self.config["record"]["dropTB"])
        createTradeTable(session=self.session, tableName=self.config["record"]["tradeTable"],
                         dropTB=self.config["record"]["dropTB"])
        createOrderTable(session=self.session, tableName=self.config["record"]["orderTable"],
                         dropTB=self.config["record"]["dropTB"])

        # 行情数据类
        self.priceDict: Dict[str, float] = {}   # 最新价字典 -> on_start中初始化为infiniTrader.xlsx中的值
        # 由于不做股指+国债期货(即CFX交易所的品种), 所以这里直接日盘取连续的就好, 回调中统一处理1015+1130+1330这三个断点
        with open(self.config["infoFile"], "r", encoding="utf-8") as f:
            self.infoDict = json5.load(f)
        self.deleteProduct: List[str] = self.config["deleteProduct"]         # 禁止下单+监控的品种
        # 所有需要被监视的合约+交易所(为了节省轮寻时间 -> 只对需要交易的品种进行实时监控)
        self.monitorContract: List[str] = []    # 需要监视的合约
        self.monitorExchange: List[str] = []    # 对应的交易所代码
        self.oriPosDict: Dict[str, Dict[str, Dict[str, Position]]] = {}  # 获取当前账号所有持仓
        self.market_center: MarketCenter = MarketCenter()  # 行情获取中心
        self.kline_generators: Dict[str, KLineGenerator] = {}  # 所有品种的1分钟K线合成器
        self.kline_containers: Dict[str, KLineContainer] = {}  # 所有品种的1分钟K线储存器

    def on_start(self) -> None:
        """策略启动的回调函数"""
        # 初始化K线合成器
        super().on_start()

        # 初始化pathStr
        if not os.path.exists(path=self.pathStr):
            os.mkdir(self.pathStr)

        # 获取当前所有持仓
        self.oriPosDict = self.get_all_position()  # TODO: 如何将oriPosDict注册进myPosition(当本地持仓文件缺失的时候)
        self.output("[INFO] 当前持仓: ")
        self.output(self.oriPosDict)

        # 本地加载Position + Order -> myPosition & myOrder初始化
        self.myPosition.inputPos(direction="long", savePath=self.pathStr, fileName=self.longPosFile)
        self.myPosition.inputPos(direction="short", savePath=self.pathStr, fileName=self.shortPosFile)
        self.myOrder.inputOrder(savePath=self.pathStr, fileName=self.orderFile)
        currentPosContract = list(set(list(self.myPosition.longPos.keys())+list(self.myPosition.shortPos.keys())))     # 当前持仓合约

        # priceDict初始化
        mainContDF = pd.read_excel(rf"{self.pathStr}\{self.config['record']['infiniFile']}", index_col=None, header=0)
        self.priceDict = dict(zip(mainContDF["合约代码"], mainContDF["最新"]))

        # 向基本信息表中添加查询后的合约信息
        self.deleteProduct = product_formatter(productList=self.deleteProduct, infoDict=self.infoDict)
        contractInfo = get_info(self=self, monitorProduct=None, deleteProduct=self.deleteProduct)
        self.session.upload({"contractInfo": contractInfo})
        self.session.run(f"""objByName("{self.infoTable}", true).append!(contractInfo)""")
        self.output("""[INFO] 合约信息加载完毕""")

        # 删除不需要的infoDict + 更新主力合约代码 & 保证金率至infoDict
        for product in self.deleteProduct:
            if product in self.infoDict:
                del self.infoDict[product]
        mainContractInfo = contractInfo[contractInfo["isMainContract"] == 1].reset_index(drop=True)  # 这里isMainContract都是1, 这样写为了方便后续拓展
        mainContractDict = dict(zip(mainContractInfo["product"], mainContractInfo["contract"]))
        mainLongMarginRateDict = dict(zip(mainContractInfo["product"], mainContractInfo["longMarginRate"]))
        mainShortMarginRateDict = dict(zip(mainContractInfo["product"], mainContractInfo["shortMarginRate"]))
        for product, info in self.infoDict.items():
            self.infoDict[product]["mainContract"] = mainContractDict[product]
            self.infoDict[product]["longMarginRate"] = mainLongMarginRateDict[product]
            self.infoDict[product]["shortMarginRate"] = mainShortMarginRateDict[product]
        self.output("""[INFO] infoDict更新完毕""")

        # 本地加载未完成订单
        addHistEvents(self)
        self.output("""[INFO] 加载未完成订单""")

        # 本地加载开仓信号 + 规范品种&合约名称 -> 没有则跳过
        toOpenContract: List[str] = []  # 需要新开的合约
        if self.signalFile:     # 如果有signalFile
            openSignal = pd.read_csv(self.signalFile, index_col=None, header=0).rename(columns={"contract": "symbol"})
            openSignal["product"] = product_formatter(productList=list(openSignal["product"]), infoDict=self.infoDict)
            openSignal["symbol"] = contract_formatter(contractList=list(openSignal["symbol"]), infoDict=self.infoDict)
            openSignal = openSignal[~openSignal["product"].isin(self.deleteProduct)].reset_index(drop=True)  # 剔除黑名单品种
            toOpenContract = list(openSignal["symbol"])
            addOpenEvents(self=self, data=openSignal, info=contractInfo)
            self.output("""[INFO] 本地加载信号完毕""")
        else:
            self.output("""[INFO] 本地加载信号为空""")
        for event in self.eventWait.values():
            self.output(event.__dict__)

        # 监控任务: 决定本次运行所有需要监视的合约 + 交易所
        contractList = list(set(currentPosContract+toOpenContract))  # 所有监控合约 = 上次持仓+本次新开
        self.monitorContract = contract_formatter(contractList=contractList, infoDict=self.infoDict)
        productList = list(["".join([j for j in i if str(j).isalpha()]) for i in self.monitorContract])   # 当前持仓品种
        self.monitorExchange = [self.infoDict[product]["exchange"] for product in productList]
        self.output(f"[INFO] 准备监控合约: {self.monitorContract}")
        # 每个合约获取最近1根1分钟K线
        for exchange, contract in zip(self.monitorExchange, self.monitorContract):
            kline_generator = KLineGenerator(
                # real_time_callback=self.on_bar_realTime,
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
            # kline_generator.push_history_data()
            self.kline_generators[contract] = kline_generator
            self.kline_containers[contract] = kline_container
        # 每个合约订阅行情
        for exchange, contract in zip(self.monitorExchange, self.monitorContract):
            self.sub_market_data(
                exchange=exchange,
                instrument_id=contract
            )
        self.output(f"[INFO] 监控合约: {self.monitorContract}")

    def on_tick(self, tick: TickData) -> None:
        """tick回调函数 -> 用于用户级别开平仓"""
        self.kline_generators[tick.instrument_id].tick_to_kline(tick, push=True)
        self.priceDict[tick.instrument_id] = tick.last_price

    def on_order(self, order: OrderData) -> None:
        """
        订单回调函数 -> 用于记录订单信息
        实时写入DolphinDB流表
        """
        super().on_order(order)
        direction: str = "long" if int(order.direction) == 0 else "short"
        status = order.status
        orderId = order.order_id
        if status == "全部成交":
            self.eventDoing[orderId].delete = True
        elif status == "部分成交":
            self.eventDoing[orderId].delete = False
            self.eventDoing[orderId].vol = order.total_vol - order.traded_vol
        else:
            self.eventDoing[orderId].delete = True
        # 总之无事发生->仍在eventDoing队列中
        # DolphinDB记录订单信息
        tableName = self.config["record"]["orderTable"]
        rowData = [order.exchange,order.instrument_id,order.price,order.order_id,order.order_sys_id,
                   int(order.order_price_type),int(order.direction),int(order.offset),pd.Timestamp(order.cancel_time),
                   pd.Timestamp(order.order_time),str(order.status),str(order.memo),pd.Timestamp.now()]
        self.session.run(f"tableInsert{ {tableName} }", rowData)

    def on_cancel(self, order: OrderData) -> None:
        """撤单推送回调"""
        super().on_cancel(order)
        self.output(f"[Msg] 撤单成功: {order.__dict__}")
        return

    def on_trade(self, trade: TradeData, log: bool = False) -> None:
        """成交回调函数"""
        # TODO: 需要考虑部分成交的订单-> 此时不能直接删除这个Order
        super().on_trade(trade, log)
        # 从eventDoing中移除对应的报单编号
        orderId = trade.order_id
        event = self.eventDoing[orderId]    # 原始事件
        if event.delete:
            del self.eventDoing[orderId]
        symbol = trade.symbol
        price = trade.price
        vol = trade.volume
        direction = "long" if int(trade.direction) == 0 else "short"
        offset = int(trade.offset)  # 开仓/平仓标志
        if offset == 0:     # 开仓/加仓成交
            # 计算staticHigh & staticLow
            staticHigh: float = None
            if event.upLimit:
                if direction == "long":
                    staticHigh = (1 + event.upLimit) * price
                else:
                    staticHigh = (1 + event.downLimit) * price
            staticLow: float = None
            if event.downLimit:
                if direction == "long":
                    staticLow = (1 - event.downLimit) * price
                else:
                    staticLow = (1 - event.upLimit) * price
            self.myPosition.openPos(direction=direction, symbol=symbol, price=price, vol=vol,
                                  minPosTime=event.minPosTimestamp, maxPosTime=event.maxPosTimestamp,
                                  staticHigh=staticHigh, staticLow=staticLow)
        else:  # 平仓成交: 1-平仓; 2-强平; 3-平今; 4-平昨
            self.myPosition.closePos(direction=direction, symbol=symbol, vol=vol)
        # DolphinDB记录成交信息
        tableName = self.config["record"]["tradeTime"]
        rowData = [trade.exchange,trade.instrument_id,trade.trade_id,trade.order_id,trade.order_sys_id,
            trade.trade_time,int(trade.direction),int(trade.offset),trade.price,trade.volume,
            trade.memo,pd.Timestamp.now()]
        # DolphinDB记录成交信息
        self.session.run(f"tableInsert{ {tableName} }", rowData)

    # 其他回调函数
    def on_bar(self, kline: KLineData) -> None:
        """接受K线回调"""
        symbol = kline.instrument_id
        openPrice = kline.open
        closePrice = kline.close
        currentTime = pd.Timestamp(kline.datetime)
        if self.lastMinute == int(currentTime.minute):   # 说明Bar发生了变动 -> 下一个时间截面
            return
        self.output(f"{kline.symbol}-{pd.Timestamp.now()} onBar trigger")
        self.lastMinute = int(currentTime.minute)
        # 1. 开平仓事件
        deleteList: List[int] = []  # 需要被删除的事件编号
        for idx, event in self.eventWait.items():
            # 获取基本信息
            symbolStr = event.symbol
            productStr = "".join([i for i in symbolStr if str(i).isalpha()])
            directionStr = "buy" if event.direction == "long" else "sell"
            exchangeStr = self.infoDict[productStr]["exchange"]
            self.eventIdx += 1
            if event.state == "open":   # 开仓事件
                orderId: int = self.send_order(
                    exchange=exchangeStr,
                    instrument_id=symbolStr,
                    volume=event.vol,
                    price=self.priceDict[symbolStr],
                    order_direction=directionStr,
                    order_type="FAK",  # 报单指令
                    market=False,    # true: 市价单成交 false: 限价单成交
                    memo=str(self.eventIdx)
                )
                self.output(f"[INFO] 下单成功-orderId:{orderId}")
            else:   # 平仓事件
                orderId: int = self.auto_close_position(
                    exchange=exchangeStr,
                    instrument_id=symbolStr,
                    order_direction=directionStr,
                    volume=event.vol,
                    price=self.priceDict[symbolStr],
                    order_type="FAK",
                    shfe_close_first=True,
                    market=False,  # true: 市价单成交 false: 限价单成交
                    memo=str(self.eventIdx)
                )
                self.output(f"[INFO] 下单成功-orderId:{orderId}")
            if orderId not in [-1, None]:   # 执行成功
                self.eventDoing[orderId] = event
                deleteList.append(idx)
            else:   # 执行失败
                continue
        if deleteList:
            for idx in deleteList:
                del self.eventWait[idx]
        self.output(f"[INFO] 当前分钟:{self.lastMinute}:当前eventWait:{self.eventWait}")
        # 2. 多仓: 持仓时间+止盈止损监控事件
        for symbol in self.myPosition.longPos:
            productStr = "".join([i for i in symbol if str(i).isalpha()])
            exchangeStr = self.infoDict[productStr]["exchange"]
            posList: List[Dict[str, any]] = self.myPosition.longPos[symbol]
            price = self.priceDict[symbol]  # 最新价
            # 止盈止损FIFO触发
            totalVol: int = 0
            for pos in posList:
                if pos["minPosTime"]:
                    if currentTime <= pos["minPosTime"]:
                        break   # 不需要平仓 + 后面的仓位也不需要检测
                if pos["maxPosTime"]:
                    if currentTime >= pos["maxPosTime"]:
                        totalVol += pos["vol"]
                        continue
                if pos["staticHigh"]:
                    if pos["staticHigh"] <= price:  # 静态最高价
                        totalVol += pos["vol"]
                        continue
                if pos["staticLow"]:
                    if pos["staticLow"] >= price:  # 静态最低价
                        totalVol += pos["vol"]
                        continue
            if totalVol > 0:    # 多单持仓 -> 卖平
                orderId: int = self.auto_close_position(
                    exchange=exchangeStr,
                    instrument_id=symbol,
                    order_direction="sell",  # Literal["buy","sell"]
                    volume=totalVol,
                    price=self.priceDict[symbol],
                    order_type="GFD",
                    shfe_close_first=True,
                    market=True,  # true: 市价单成交 false: 限价单成交
                    memo=str(self.eventIdx)
                )
                self.output(f"[INFO] 多单平仓-{productStr}-{symbol}-{totalVol}下单状态:{orderId}")
                if orderId not in [-1, None]:   # 下单成功:
                    self.eventIdx += 1
                    E = OrderCloseEvent(symbol=symbol, direction="long", vol=totalVol, memo=str(self.eventIdx))
                    self.eventDoing[orderId] = E  # 这里跳过eventWait, 直接加入eventDoing
                else:   # 下单失败 -> 这里的处理方式是跳过, TODO: 改为别的处理方式
                    continue

        # 2. 空仓: 持仓时间+止盈止损监控事件
        for symbol in self.myPosition.shortPos:
            productStr = "".join([i for i in symbol if str(i).isalpha()])
            exchangeStr = self.infoDict[productStr]["exchange"]
            posList: List[Dict[str, any]] = self.myPosition.shortPos[symbol]
            price = self.priceDict[symbol]  # 最新价
            # 止盈止损FIFO触发
            totalVol: int = 0
            for pos in posList:
                if pos["minPosTime"]:
                    if currentTime <= pos["minPosTime"]:
                        break   # 不需要平仓 + 后面的仓位也不需要检测
                if pos["maxPosTime"]:
                    if currentTime >= pos["maxPosTime"]:
                        totalVol += pos["vol"]
                        continue
                if pos["staticHigh"]:
                    if pos["staticHigh"] <= price:  # 静态最高价
                        totalVol += pos["vol"]
                        continue
                if pos["staticLow"]:
                    if pos["staticLow"] >= price:  # 静态最低价
                        totalVol += pos["vol"]
                        continue
            if totalVol > 0:  # 空单持仓 -> 卖平
                orderId: int = self.auto_close_position(
                    exchange=exchangeStr,
                    instrument_id=symbol,
                    order_direction="buy",  # Literal["buy","sell"]
                    volume=totalVol,
                    price=self.priceDict[symbol],
                    order_type="GFD",
                    shfe_close_first=True,
                    market=True,  # true: 市价单成交 false: 限价单成交
                    memo=str(self.eventIdx)
                )
                self.output(f"[INFO] 空单平仓-{productStr}-{symbol}-{totalVol}下单状态:{orderId}")
                if orderId not in [-1, None]:   # 下单成功:
                    self.eventIdx += 1
                    E = OrderCloseEvent(symbol=symbol, direction="short", vol=totalVol, memo=str(self.eventIdx))
                    self.eventDoing[orderId] = E  # 这里跳过eventWait, 直接加入eventDoing
                else:   # 下单失败 -> 这里的处理方式是跳过, TODO: 改为别的处理方式
                    continue

    def on_bar_realTime(self, kline: KLineData) -> None:
        """接受实时K线回调"""
        return

    def on_stop(self) -> None:
        """策略暂停/终止回调"""
        super().on_stop()

        # 每个合约取消订阅行情
        for exchange, contract in zip(self.monitorExchange, self.monitorContract):
            self.unsub_market_data(
                exchange=exchange,
                instrument_id=contract
            )
        self.output(f"[INFO] 取消订阅行情: {self.monitorContract}")
        # 保存订单信息 & 保存持仓信息
        self.myPosition.outputPos(direction="long", savePath=self.pathStr, fileName=self.longPosFile)
        self.myPosition.outputPos(direction="short", savePath=self.pathStr, fileName=self.shortPosFile)
        self.output("[INFO] Position 状态信息Json5保存完毕")
        self.myOrder.outputOrder(savePath=self.pathStr, fileName=self.orderFile)
        self.output("[INFO] Order 状态信息Json5保存完毕")

