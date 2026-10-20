package com.ganfeng.rs.common;

import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import com.ganfeng.rs.role.RoleStore;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.stereotype.Component;

import java.util.Set;
import java.util.stream.Collectors;

/**
 * 权限校验器：按"操作权限点"动态判定
 * 权限从角色实时解析——管理员改了角色权限，下一次请求立即生效，无需对方重新登录
 *
 * 同时承载**项目数据隔离**校验（requireAccess）：纵向权限管"能不能做这个操作"，
 * 横向权限管"能不能碰这个项目的数据"，两者缺一不可。
 */
@Component
public class PermissionGuard {

    private final RoleStore roleStore;
    private final ProjectService projectService;

    public PermissionGuard(RoleStore roleStore, ProjectService projectService) {
        this.roleStore = roleStore;
        this.projectService = projectService;
    }

    /** 当前用户的角色编码集合（JWT role claim 已被过滤器转成 ROLE_XXX） */
    public Set<String> roleCodesOf(Authentication auth) {
        return auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .map(a -> a.startsWith("ROLE_") ? a.substring(5) : a)
                .collect(Collectors.toSet());
    }

    public boolean has(Authentication auth, String actionPerm) {
        return roleCodesOf(auth).stream()
                .anyMatch(code -> roleStore.actionPermsOf(code).contains(actionPerm));
    }

    public void require(Authentication auth, String actionPerm) {
        if (!has(auth, actionPerm)) {
            throw new BizException(403, "当前角色无权执行此操作");
        }
    }

    /**
     * 校验当前用户是否为管理员（管理员可跨项目访问）
     */
    public boolean isAdmin(Authentication auth) {
        return roleCodesOf(auth).contains("ADMIN");
    }

    /**
     * 校验当前用户对某项目的访问权（项目数据隔离的横向防护）。
     * 管理员直通；其他角色必须在 project_members 关联表内。
     */
    public void requireAccess(Long projectId, Authentication auth) {
        if (isAdmin(auth)) {
            return;
        }
        if (projectId == null) {
            throw new BizException(400, "缺少项目参数");
        }
        var visible = projectService.listForUser(auth.getName(), false).stream()
                .map(Project::getId)
                .toList();
        if (!visible.contains(projectId)) {
            throw new BizException(403, "你不在该项目的成员清单中，无权访问");
        }
    }

    /** 供控制器复用的重载（isAdmin 已在控制器算好时避免重复解析） */
    public void requireAccess(Long projectId, String username, boolean isAdmin) {
        if (isAdmin) {
            return;
        }
        if (projectId == null) {
            throw new BizException(400, "缺少项目参数");
        }
        var visible = projectService.listForUser(username, false).stream()
                .map(Project::getId)
                .toList();
        if (!visible.contains(projectId)) {
            throw new BizException(403, "你不在该项目的成员清单中，无权访问");
        }
    }
}
