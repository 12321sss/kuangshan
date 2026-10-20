package com.ganfeng.rs.role;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 角色管理控制器
 * 查看（列表/权限目录）全员开放——前端渲染菜单和用户表单需要；
 * 增删改需要 action:role-manage 权限
 */
@RestController
@RequestMapping("/api/roles")
public class RoleController {

    private final RoleStore roleStore;
    private final PermissionGuard guard;

    public RoleController(RoleStore roleStore, PermissionGuard guard) {
        this.roleStore = roleStore;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<Role>> list() {
        return ApiResponse.ok(roleStore.list());
    }

    /** 权限点目录：前端角色编辑器的勾选矩阵数据源 */
    @GetMapping("/catalog")
    public ApiResponse<Map<String, Object>> catalog() {
        return ApiResponse.ok(Map.of("pages", PermCatalog.PAGES, "actions", PermCatalog.ACTIONS));
    }

    @PostMapping
    public ApiResponse<Role> create(@RequestBody Role req, Authentication auth) {
        guard.require(auth, "action:role-manage");
        return ApiResponse.ok(roleStore.create(req));
    }

    @PutMapping("/{code}")
    public ApiResponse<Role> update(@PathVariable String code, @RequestBody Role req, Authentication auth) {
        guard.require(auth, "action:role-manage");
        return ApiResponse.ok(roleStore.update(code, req));
    }

    @DeleteMapping("/{code}")
    public ApiResponse<Void> delete(@PathVariable String code, Authentication auth) {
        guard.require(auth, "action:role-manage");
        roleStore.delete(code);
        return ApiResponse.ok(null);
    }
}
