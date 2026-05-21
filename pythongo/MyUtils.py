import pandas as pd
import dolphindb as ddb
from typing import List, Dict

def product_formatter(productList: List[str], infoDict: Dict[str, Dict[str, any]]) -> List[str]:
    """把品种代码映射为无限易的代码"""
    lower_product_list = [str(i).lower() for i in infoDict.keys()]
    format_product_list = list(infoDict.keys())
    resultList: List[str] = []
    for i in productList:
        formatted_product = str(i).lower()
        if formatted_product in lower_product_list:
            idx = lower_product_list.index(formatted_product)
            resultList.append(format_product_list[idx])
        else:
            resultList.append(i)    # 原来啥样就是啥样
    return resultList

def contract_formatter(contractList: List[str], infoDict: Dict[str, Dict[str, any]]) -> List[str]:
    """把合约代码映射为无限易的代码"""
    contractList = [str(i).split(".")[0] for i in contractList]  # AU2601.SHF -> AU2601
    productList = ["".join([j for j in str(i) if str(j).isalpha()]) for i in contractList]
    timeList = ["".join([j for j in str(i) if str(j).isdigit()]) for i in contractList]
    productList_format = product_formatter(productList=productList, infoDict=infoDict)
    integerList = [infoDict[product]["format"] for product in productList_format]
    resultList = []
    for i in range(0, len(productList_format)):
        product = productList_format[i]
        year = timeList[i] if integerList[i] == 4 else timeList[i][1:]
        resultList.append(str(product) + str(year))
    return resultList

def createInfoTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """DolphinDB 合约信息流表"""
    colNames = ["product", "exchange", "contract", "multi", "longMarginRate", "shortMarginRate", "hasNightTrade",
                "openTime", "closeTime", "nightOpenTime", "nightCloseTime", "dayOpenTime", "dayCloseTime", "isMainContract"]
    colTypes = ["SYMBOL", "SYMBOL", "SYMBOL", "INT", "DOUBLE", "DOUBLE", "INT",
                "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "INT"]
    # hasNightTrade: 是否有夜盘交易 -> openTime = iif(hasNightTrade == 1, nightOpenTime, dayOpenTime);  closeTime = dayCloseTime
    # xxxTime -> 全部以24小时制分钟计时
    session.upload({"colNames": colNames, "colTypes": colTypes})
    session.run(f"""
    if ({int(dropTB)} == 1){{
        try{{undef("{tableName}", SHARED)}}catch(ex){{}}; // 先删除共享表
    }};
    tab = table(1:0, colNames, colTypes);
    share(tab, "{tableName}"); // 创建共享内存表
    """)

def createOrderTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """DolphinDB 订单流表"""
    colNames = ["exchange", "contract", "price", "orderId", "orderSysId",
                "orderPriceType", "direction", "offset", "cancelTime", "orderTime", "currentTime"]
    colTypes = ["SYMBOL", "SYMBOL", "DOUBLE", "INT", "STRING",
                "INT", "INT", "INT", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP"]
    # orderPriceType 需要 string -> int
    # direction 需要 string -> int
    # cancelTime&orderTime 需要 string -> pd.Timestamp
    session.upload({"colNames": colNames, "colTypes": colTypes})
    session.run(f"""
    if ({int(dropTB)} == 1){{
        try{{undef("{tableName}", SHARED)}}catch(ex){{}}; // 先删除共享表
    }};
    tab = table(1:0, colNames, colTypes);
    share(tab, "{tableName}"); // 创建共享内存表
    """)

def createTradeTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """"DolphinDB 交易流表"""
    colNames = ["exchange", "contract", "tradeId", "orderId", "orderSysId", "tradeTime",
                "direction", "offset", "price", "volume", "currentTime"]
    colTypes = ["SYMBOL", "SYMBOL", "INT", "INT", "INT", "TIMESTAMP",
                "INT", "INT", "DOUBLE", "INT", "TIMESTAMP"]
    # direction 需要 string -> int
    session.upload({"colNames": colNames, "colTypes": colTypes})
    session.run(f"""
    if ({int(dropTB)} == 1){{
        try{{undef("{tableName}", SHARED)}}catch(ex){{}}; // 先删除共享表
    }};
    tab = table(1:0, colNames, colTypes);
    share(tab, "{tableName}"); // 创建共享内存表
    """)

def process_marginRate(filePath: str, infoDict: Dict[str, Dict[str, any]], savePath: str = None, fileName: str = None) -> pd.DataFrame:
    """
    FROM交易星球: https://www.jiaoyixingqiu.com/shouxufei/all -> 规整的DataFrame格式
    product contract openMarginRate closeMarginRate margin
    savePath为None时不保存
    """
    # 尝试用 HTML 读取
    tables = pd.read_html(filePath,header=2,index_col=None,encoding="utf-8")
    data = tables[0][["合约代码","买开%","卖开%","保证金/元","备注"]]
    data.columns = ["contract","longMarginRate","shortMarginRate","margin","isMainContract"]
    # 去除合约代码包含中文字符的行
    data = data[~data['contract'].str.contains(r'[\u4e00-\u9fff]', na=False)].reset_index(drop=True)
    # 去除合约代码以字母结尾的行
    data = data[~data['contract'].str[-1].str.isalpha()].reset_index(drop=True)
    data["contract"] = contract_formatter(contractList=list(data["contract"]), infoDict=infoDict)
    data["longMarginRate"] = data["longMarginRate"].apply(lambda x: float(str(x).replace("%",""))/100)    # %->float
    data["shortMarginRate"] = data["shortMarginRate"].apply(lambda x: float(str(x).replace("%",""))/100)    # %->float
    data["margin"] = pd.to_numeric(data["margin"])
    data["isMainContract"] = data["isMainContract"].apply(lambda x: 1 if x == "主力" else 0)  # 主力合约标志
    if savePath and fileName:
        data.to_csv(rf"{savePath}\{fileName}", index=None)
    return data

if __name__ == "__main__":
    infoDict = {'AP': {'exchange': 'CZCE', 'multi': 10, 'format': 3, 'nightTime': False, 'dayTime': [900, 1500]},
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
    data = process_marginRate(filePath=r"E:\Quant\QuantTrader\infiniTrader\cons\0522.xls",
                              infoDict=infoDict, savePath=r"E://Quant//QuantTrader//infiniTrader//cons",
                              fileName="marginInfo.csv")
    print(data["contract"].tolist())
    df = pd.read_excel(r"E:\Quant\QuantTrader\infiniTrader\cons\infiniTrader.xlsx",index_col=None,header=0)
    print(df)
    # multiDict = dict(zip(df["品种"],df["合约乘数"]))
    # print({product: {"exchange": list_[0], "multi": multiDict[product], "format": list_[1], "nightTime": list_[2], "dayTime": list_[3]}
    #     for product, list_ in infoDict.items()
    # })