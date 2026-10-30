"""算法层（纯计算，不依赖 FastAPI）。

约定
----
- 这一层只做「读数据 → 算 → 返回 dict/list」，**不 import fastapi、不碰 HTTP**，
  这样可以直接被脚本、notebook、单元测试调用。
- 每个模块暴露一个主函数（classify / analyze / evaluate / extract_class …），
  入参是 dict，返回可 JSON 序列化的 dict，方便路由层原样转发。
- 模块之间允许互相调用，但一律用相对导入（`from . import dem`），
  这样整个包可以被搬到任意目录而不改代码。

模块分工
--------
classify / supervised / supervised_local   地物分类（指数法、S2 监督、本地高分监督）
sentinel / sentinel_source                 在线影像获取（AWS STAC / 场景检索）
change                                      时序变化与影像可用性
dem / slope / risk / spatial                地形、边坡、安全、空间关系
fusion                                      分类结果 × 指数结果一致性
ecology / report                            生态指数、Word 报告
aoi_import / imagery_probe                  边界文件解析、影像元数据识别
"""
