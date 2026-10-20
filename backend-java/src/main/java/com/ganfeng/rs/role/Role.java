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

    public void setName(String name) { this.name = name; }
    public void setDescription(String description) { this.description = description; }
    public void setPagePerms(List<String> pagePerms) { this.pagePerms = pagePerms; }
    public void setActionPerms(List<String> actionPerms) { this.actionPerms = actionPerms; }
}
