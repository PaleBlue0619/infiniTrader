# 预计实现功能
0. 系统幂等性, 盘中多次重启策略后不影响交易与监控行为 <br>
1. 维护infoTable, 每日更新主力合约代码+多头/空头保证金率并汇总为DolphinDB流表, 同时根据策略启动时间更新流表中日盘/夜盘交易时间字段(由于无限易每日盘后交易所柜台必定主动断开连接, 故该逻辑合理)
2. 根据开仓csv信号文件, 实现多合约多方向同时下单(盘前启动则开盘下单, 盘中启动则盘中下单) <br>
3. 订单/仓位对象加载与保存, 自定义MyOrder与MyPosition类序列化为json5文件 <br>
4. 支持静态止盈止损+最短/最长持仓时间设置, 在开仓csv信号文件中设置即可(FIFO触发, 时间优先原则: 最短持仓时间前禁止平仓), <br>
   后续将同时支持动态止盈止损设置并重构参数 <br>
5. 实时订单/交易行为写入DolphinDB流表, 便于事后分析, 后续将开启DolphinDB流表持久化功能  <br>

# 注
pythongo与self_strategy文件夹分别对应C:\Users\Admin\AppData\Roaming\InfiniTrader_WxyAllProgramX64\pyStrategy下的对应文件夹的新增/修改文件 
-> 基于pythongo源码进行魔改 <br>
