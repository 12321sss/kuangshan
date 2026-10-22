package com.ganfeng.rs.role;

import java.util.List;
import java.util.Map;

/**
 * 权限点目录：全平台所有可分配的页面与操作
 *
 * 前端角色管理页的勾选矩阵、后端接口校验、前端菜单过滤共用这套编码。
 *
 * 2026-10-22 重构：原目录只有 15 个页面点，而平台已有 25+ 个功能页，
 * 导致 page:analysis 一个点管着「时序/安全/边坡/空间/地形/生态/报告/融合」8 个页面，
 * page:extract 管着 5 个页面——无法按页面单独授权，客户提"我只让某角色看生态指数"就做不到。
 * 本次按业务分组拆细，并给每个点补 group 字段供前端分组展示。
 */
public final class PermCatalog {

    private PermCatalog() {}

    /** 业务分组名，前端按此顺序分组渲染 */
    public static final List<String> GROUPS = List.of(
            "总览", "数据准备", "解译作业", "持续监测", "结果比对",
            "监测告警", "变化分析", "安全与生态评估", "成果输出", "平台管理");

    private static Map<String, String> p(String code, String name, String group) {
        return Map.of("code", code, "name", name, "group", group);
    }

    /** 页面可见性权限点（与左侧菜单入口对应） */
    public static final List<Map<String, String>> PAGES = List.of(
            // 总览
            p("page:dashboard", "总览", "总览"),

            // 数据准备
            p("page:imagery", "影像库", "数据准备"),
            p("page:boundary", "边界管理", "数据准备"),

            // 解译作业
            p("page:extract", "在线解译", "解译作业"),
            p("page:classify", "监督分类", "解译作业"),
            p("page:extract-local", "本地解译", "解译作业"),

            // 持续监测
            p("page:change-monitor", "变化监测", "持续监测"),

            // 结果比对
            p("page:compare", "数据对比", "结果比对"),
            p("page:fusion", "结果融合", "结果比对"),

            // 监测告警
            p("page:monitor", "设备监测", "监测告警"),
            p("page:ops-stations", "站点监控", "监测告警"),
            p("page:warning-rules", "预警设置", "监测告警"),
            p("page:warning-alarms", "告警日志", "监测告警"),

            // 变化分析
            p("page:analysis", "时序与构成", "变化分析"),

            // 安全与生态评估
            p("page:safety", "综合安全评估", "安全与生态评估"),
            p("page:slope", "边坡单元", "安全与生态评估"),
            p("page:spatial", "空间关系", "安全与生态评估"),
            p("page:terrain", "地形分析", "安全与生态评估"),
            p("page:ecology", "生态指数", "安全与生态评估"),

            // 成果输出
            p("page:report", "报告生成", "成果输出"),
            p("page:screen", "GIS 大屏", "成果输出"),

            // 平台管理
            p("page:projects", "项目管理", "平台管理"),
            p("page:users", "用户中心", "平台管理"),
            p("page:roles", "角色管理", "平台管理"),
            p("page:audit-logs", "操作日志", "平台管理"),
            p("page:dict", "数据字典", "平台管理"),
            p("page:health", "系统健康", "平台管理"),
            p("page:trash", "回收站", "平台管理")
    );

    /** 操作权限点（写操作与耗时操作，与页面可见性分离） */
    public static final List<Map<String, String>> ACTIONS = List.of(
            // 数据准备
            p("action:imagery-manage", "影像上传/删除", "数据准备"),
            p("action:boundary-manage", "边界导入/删除", "数据准备"),

            // 解译作业
            p("action:extract-manage", "解译执行/删除", "解译作业"),
            p("action:classify-manage", "监督分类训练/样本入库", "解译作业"),
            p("action:watch-manage", "关注区新增/删除", "解译作业"),

            // 安全与生态评估
            p("action:safety-evaluate", "执行安全评估", "安全与生态评估"),
            p("action:ecology-evaluate", "计算生态指数", "安全与生态评估"),
            p("action:terrain-analyze", "地形分析", "安全与生态评估"),

            // 成果输出
            p("action:report-generate", "生成/下载报告", "成果输出"),
            p("action:export", "导出 GeoJSON / GeoTIFF / CSV", "成果输出"),

            // 监测告警
            p("action:alarm-ack", "告警确认", "监测告警"),
            p("action:rule-edit", "预警规则编辑", "监测告警"),
            p("action:station-manage", "站点增删改", "监测告警"),

            // 平台管理
            p("action:project-manage", "项目增删改/成员分配", "平台管理"),
            p("action:user-manage", "用户增删改", "平台管理"),
            p("action:role-manage", "角色增删改", "平台管理"),
            p("action:dict-manage", "数据字典维护", "平台管理"),
            p("action:trash-manage", "回收站恢复/彻底删除", "平台管理")
    );
}
