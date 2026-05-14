from typing import Literal, Dict, List

# 从 base 库中导入定义参数和状态映射模型必须的三个方法
from pythongo.base import BaseParams, BaseState, Field, BaseStrategy
from pythongo.classdef import KLineData, OrderData, TickData, TradeData
from pythongo.core import KLineStyleType, MarketCenter
from pythongo.utils import KLineGenerator

def product_formatter(productList: List[str], formatDict: Dict[str, List]) -> List[str]:
    """把品种代码映射为无限易的代码"""
    lower_product_list = [str(i).lower() for i in formatDict.keys()]
    format_product_list = list(formatDict.keys())
    format_value_list = list(formatDict.values())
    resultList: List[str] = []
    for i in productList:
        formatted_product = str(i).lower()
        idx = lower_product_list.index(formatted_product)
        resultList.append(format_product_list[idx])
    return resultList

def contract_formatter(contractList: List[str], formatDict: Dict[str, List]) -> List[str]:
    """把合约代码映射为无限易的代码"""
    contractList = [str(i).split(".")[0] for i in contractList] # AU2601.SHF -> AU2601
    productList = ["".join([j for j in str(i) if str(j).isalpha()]) for i in contractList]
    timeList = ["".join([j for j in str(i) if str(j).isdigit()]) for i in contractList]
    productList_format = product_formatter(productList=productList, formatDict=formatDict)
    integerList = [formatDict[product][-1] for product in productList_format]
    resultList = []
    for i in range(0, len(productList_format)):
        product = productList_format[i]
        year = timeList[i] if integerList[i] == 4 else timeList[i][1:]
        resultList.append(str(product)+str(year))
    return resultList

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

class myStrategy(BaseStrategy):
    """实盘策略主体
    在编写回调函数时, 回调函数应当按照以下顺序定义, 用不到的回调函数允许不定义
    """
    def __init__(self) -> None:
        super().__init__()
        self.formatDict = {
            "AP": ["CZCE", 3], # 交易所 # 是否省略2
            "CF": ["CZCE", 3],
            "CJ": ["CZCE", 3],
            "CY": ["CZCE", 3],
            "FG": ["CZCE", 3],
            "IC": ["CFFEX", 4],
            "IF": ["CFFEX", 4],
            "IH": ["CFFEX", 4],
            "IM": ["CFFEX", 4],
            "JR": ["CZCE", 3],
            "MA": ["CZCE", 3],
            "OI": ["CZCE", 3],
            "PF": ["CZCE", 3],
            "PK": ["CZCE", 3],
            "PL": ["CZCE", 3],
            "PM": ["CZCE", 3],
            "PR": ["CZCE", 3],
            "PX": ["CZCE", 3],
            "RI": ["CZCE", 3],
            "RM": ["CZCE", 3],
            "RS": ["CZCE", 3],
            "SA": ["CZCE", 3],
            "SF": ["CZCE", 3],
            "SH": ["CZCE", 3],
            "SM": ["CZCE", 3],
            "SR": ["CZCE", 3],
            "T": ["CFFEX", 4],
            "TA": ["CZCE", 3],
            "TF": ["CFFEX", 4],
            "TL": ["CFFEX", 4],
            "TS": ["CFFEX", 4],
            "UR": ["CZCE", 3],
            "WH": ["CZCE", 3],
            "ZC": ["CZCE", 3],
            "a": ["DCE", 4],
            "ad": ["SHFE", 4],
            "ag": ["SHFE", 4],
            "al": ["SHFE", 4],
            "ao": ["SHFE", 4],
            "au": ["SHFE", 4],
            "b": ["DCE", 4],
            "bb": ["DCE", 4],
            "bc": ["INE", 4],
            "br": ["SHFE", 4],
            "bu": ["SHFE", 4],
            "bz": ["DCE", 4],
            "c": ["DCE", 4],
            "cs": ["DCE", 4],
            "cu": ["SHFE", 4],
            "eb": ["DCE", 4],
            "ec": ["INE", 4],
            "eg": ["DCE", 4],
            "fb": ["DCE", 4],
            "fu": ["SHFE", 4],
            "hc": ["SHFE", 4],
            "i": ["DCE", 4],
            "j": ["DCE", 4],
            "jd": ["DCE", 4],
            "jm": ["DCE", 4],
            "l": ["DCE", 4],
            "lc": ["GFFEX", 4],
            "lg": ["DCE", 4],
            "lh": ["DCE", 4],
            "lu": ["INE", 4],
            "m": ["DCE", 4],
            "ni": ["SHFE", 4],
            "nr": ["INE", 4],
            "op": ["SHFE", 4],
            "p": ["DCE", 4],
            "pb": ["SHFE", 4],
            "pd": ["GFEX", 4],
            "pg": ["DCE", 4],
            "pp": ["DCE", 4],
            "ps": ["GFEX", 4],
            "pt": ["GFEX", 4],
            "rb": ["SHFE", 4],
            "rr": ["DCE", 4],
            "ru": ["SHFE", 4],
            "sc": ["INE", 4],
            "si": ["GFEX", 4],
            "sn": ["SHFE", 4],
            "sp": ["SHFE", 4],
            "ss": ["SHFE", 4],
            "v": ["DCE", 4],
            "wr": ["SHFE", 4],
            "y": ["DCE", 4],
            "zn": ["SHFE", 4]
        }
        self.posDict: Dict[str, Dict[str, any]] = {}    # 前一个交易日收盘时的持仓状态字典
        self.monitorCont: List[str] = ["AG2606.SHF","AP2610.ZCE"]   # 所有需要被监视的合约列表
        self.monitorCont = contract_formatter(contractList=self.monitorCont, formatDict=self.formatDict)
        self.monitorExchange: List[str] = []    # 所有需要被监视的合约列表对应的交易所
        for i in self.monitorCont:
            product = "".join(j for j in i if j.isalpha())
            self.monitorExchange.append(self.formatDict[product][0])    # 被监视合约对应的交易所信息
        """
        {"AU2501": {"start_date", "end_date", "price", "static_high", "static_low"}
        }
        """
        self.market_center = MarketCenter()
        self.klineDict: Dict[str, KLineData] = {}
        self.kline_generators: dict[str, KLineGenerator] = {}    # 所有品种的1分钟K线合成器
        # 确定当日所有需要监控的品种列表(为了节省轮寻时间 -> 只对需要交易的品种进行实时监控)

    def on_init(self) -> None:
        print("init")

    def on_start(self) -> None:
        """策略启动的回调函数"""
        # 每个合约获取最近1根1分钟K线
        for exchange, contract in zip(self.monitorExchange, self.monitorCont):
            kline_generator = KLineGenerator(
                real_time_callback = None,
                callBack = None,
                exchange = exchange,
                instrument_id = contract,
                style = "M1"
            ) # 代表一分钟K线 -> 详见https://infinitrader.quantdo.com.cn/pythongo_v2/modules/pythongo_core#klinestyle

        # 每个合约订阅行情
        for exchange, contract in zip(self.monitorExchange, self.monitorCont):
            self.sub_market_data(
                exchange=exchange,
                instrument_id=contract
            )
        # 初始化K线合成器
        super().on_start()

    def on_tick(self, tick: TickData) -> None:
        """tick回调函数 -> 用于用户级别开平仓 + """
        self.output(tick)

    def on_stop(self) -> None:
        super().on_stop()

        # 每个合约取消订阅行情
        for exchange, contract in zip(self.monitorExchange, self.monitorCont):
            self.unsub_market_data(
                exchange=exchange,
                instrument_id=contract
            )
    #
    # def callback_kbar(self, kline: KLineData) -> None:
    #     """
    #     K线合成后的回调函数
    #     """
    #     # OHLCV数据
    #     # self.calc_indicator()
    #     self.update_status_bar()
    #
    #
