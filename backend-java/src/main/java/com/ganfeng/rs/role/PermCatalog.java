package com.ganfeng.rs.role;

import java.util.List;
import java.util.Map;

/**
 * 权限点目录：全平台所有可分配的页面与操作
 * 前端角色管理页的勾选矩阵、后端接口校验、前端菜单过滤共用这套编码
 */
public final class PermCatalog {

    private PermCatalog() {}

    /** 页面可见性权限点 */
    public static final List<Map<String, String>> PAGES = List.of(
            Map.of("code", "page:dashboard", "name", "总览"),
            Map.of("code", "page:monitor", "name", "监测数据"),
            Map.of("code", "page:warning-rules", "name", "预警设置"),
            Map.of("code", "page:warning-alarms", "name", "告警日志"),
            Map.of("code", "page:ops-stations", "name", "站点监控"),
            Map.of("code", "page:analysis", "name", "变化分析"),
            Map.of("code", "page:extract", "name", "在线提取"),
            Map.of("code", "page:imagery", "name", "影像库"),
            Map.of("code", "page:projects", "name", "项目管理"),
            Map.of("code", "page:users", "name", "用户中心"),
            Map.of("code", "page:roles", "name", "角色管理"),
            Map.of("code", "page:screen", "name", "GIS 大屏"),
            Map.of("code", "page:audit-logs", "name", "操作日志"),
            Map.of("code", "page:dict", "name", "数据字典"),
            Map.of("code", "page:health", "name", "系统健康")
    );

    /** 操作权限点 */
    public static final List<Map<String, String>> ACTIONS = List.of(
            Map.of("code", "action:rule-edit", "name", "预警规则编辑"),
            Map.of("code", "action:alarm-ack", "name", "告警确认"),
            Map.of("code", "action:station-manage", "name", "站点增删改"),
            Map.of("code", "action:project-manage", "name", "项目增删改/成员分配"),
            Map.of("code", "action:imagery-manage", "name", "影像上传/删除"),
            Map.of("code", "action:extract-manage", "name", "在线提取/删除"),
            Map.of("code", "action:user-manage", "name", "用户增删改"),
            Map.of("code", "action:role-manage", "name", "角色增删改")
    );
}
