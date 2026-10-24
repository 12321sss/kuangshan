package com.ganfeng.rs.role;

import com.ganfeng.rs.common.JsonStringListConverter;
import jakarta.persistence.*;

import java.util.List;

/**
 * 角色实体（roles 表）：权限存页面权限点 + 操作权限点两组 JSON 清单
 * builtin=true 的内置角色不允许删除；ADMIN 权限锁定（防系统锁死）
 */
@Entity
@Table(name = "roles")
public class Role {

    @Id
    @Column(length = 32)
    private String code;

    @Column(nullable = false, length = 64)
    private String name;

    @Column(length = 255)
    private String description;

    @Column(nullable = false)
    private boolean builtin;

    @Convert(converter = JsonStringListConverter.class)
    @Column(columnDefinition = "json")
    private List<String> pagePerms = List.of();

    @Convert(converter = JsonStringListConverter.class)
    @Column(columnDefinition = "json")
    private List<String> actionPerms = List.of();

    /**
     * 项目可见范围（2026-10-24 新增）
     *
     * 背景：权限体系原本只有「能做什么」（页面/操作），没有「能看哪个项目」。
     * 项目可见性完全靠 project_members 成员表，导致新建角色的用户登录后一个项目都看不到，
     * 必须先去「项目管理 → 成员」逐个添加，很容易漏。
     *
     * 取值：
     *   ALL      —— 全部项目（管理员用）
     *   SPECIFIC —— 仅 projectIds 里的项目
     *   NONE     —— 不预设，只按个人成员关系（向后兼容的默认值）
     *
     * 最终可见 = 角色范围 ∪ 个人成员（并集），角色配了项目的人再加个人成员不会互相覆盖。
     */
    @Column(length = 16)
    private String projectScope = "NONE";

    /** projectScope=SPECIFIC 时生效：可见项目 id 列表（存字符串，复用 JSON 转换器） */
    @Convert(converter = JsonStringListConverter.class)
    @Column(columnDefinition = "json")
    private List<String> projectIds = List.of();

    protected Role() {}

    public Role(String code, String name, String description,
                List<String> pagePerms, List<String> actionPerms, boolean builtin) {
        this.code = code;
        this.name = name;
        this.description = description;
        this.pagePerms = pagePerms;
        this.actionPerms = actionPerms;
        this.builtin = builtin;
    }

    public String getCode() { return code; }
    public String getName() { return name; }
    public String getDescription() { return description; }
    public boolean isBuiltin() { return builtin; }
    public List<String> getPagePerms() { return pagePerms; }
    public List<String> getActionPerms() { return actionPerms; }
    public String getProjectScope() { return projectScope; }
    public List<String> getProjectIds() { return projectIds; }

    public void setName(String name) { this.name = name; }
    public void setDescription(String description) { this.description = description; }
    public void setPagePerms(List<String> pagePerms) { this.pagePerms = pagePerms; }
    public void setActionPerms(List<String> actionPerms) { this.actionPerms = actionPerms; }
    public void setProjectScope(String projectScope) { this.projectScope = projectScope; }
    public void setProjectIds(List<String> projectIds) { this.projectIds = projectIds; }
}
