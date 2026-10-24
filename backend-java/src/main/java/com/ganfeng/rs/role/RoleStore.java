package com.ganfeng.rs.role;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Set;

/**
 * 角色服务（MySQL 持久化）：页面权限点 + 操作权限点两组清单
 */
@Service
public class RoleStore {

    private final RoleRepository repo;

    public RoleStore(RoleRepository repo) {
        this.repo = repo;
    }

    public List<Role> list() {
        return repo.findAll();
    }

    public Role get(String code) {
        return repo.findById(code).orElseThrow(() -> BizException.notFound("角色不存在: " + code));
    }

    /** 操作权限（ADMIN 恒为全集，不受编辑影响） */
    public List<String> actionPermsOf(String code) {
        if ("ADMIN".equals(code)) {
            return PermCatalog.ACTIONS.stream().map(a -> a.get("code")).toList();
        }
        return repo.findById(code).map(Role::getActionPerms).orElse(List.of());
    }

    /** 页面权限（ADMIN 恒为全集） */
    public List<String> pagePermsOf(String code) {
        if ("ADMIN".equals(code)) {
            return PermCatalog.PAGES.stream().map(p -> p.get("code")).toList();
        }
        return repo.findById(code).map(Role::getPagePerms).orElse(List.of());
    }

    public boolean exists(String code) {
        return repo.existsById(code);
    }

    @Transactional
    public Role create(Role req) {
        if (repo.existsById(req.getCode())) {
            throw BizException.badRequest("角色编码已存在: " + req.getCode());
        }
        validatePerms(req.getPagePerms(), req.getActionPerms());
        validateScope(req.getProjectScope());
        Role r = new Role(req.getCode(), req.getName(), req.getDescription(),
                req.getPagePerms(), req.getActionPerms(), false);
        r.setProjectScope(normalizeScope(req.getProjectScope()));
        r.setProjectIds(req.getProjectIds() == null ? List.of() : req.getProjectIds());
        return repo.save(r);
    }

    @Transactional
    public Role update(String code, Role req) {
        Role existing = get(code);
        if ("ADMIN".equals(code)) {
            throw BizException.badRequest("内置管理员角色权限锁定，不可修改");
        }
        validatePerms(req.getPagePerms(), req.getActionPerms());
        existing.setName(req.getName());
        existing.setDescription(req.getDescription());
        existing.setPagePerms(req.getPagePerms());
        existing.setActionPerms(req.getActionPerms());
        // 项目可见范围（2026-10-24）：与页面/操作权限一起保存
        validateScope(req.getProjectScope());
        existing.setProjectScope(normalizeScope(req.getProjectScope()));
        existing.setProjectIds(req.getProjectIds() == null ? List.of() : req.getProjectIds());
        return repo.save(existing);
    }

    @Transactional
    public void delete(String code) {
        Role existing = get(code);
        if (existing.isBuiltin()) {
            throw BizException.badRequest("内置角色不允许删除");
        }
        repo.delete(existing);
    }

    /** 项目范围取值校验：只允许 ALL / SPECIFIC / NONE */
    private void validateScope(String scope) {
        if (scope == null || scope.isBlank()) return;
        if (!Set.of("ALL", "SPECIFIC", "NONE").contains(scope)) {
            throw BizException.badRequest("非法项目范围: " + scope + "（只允许 ALL / SPECIFIC / NONE）");
        }
    }

    private String normalizeScope(String scope) {
        return (scope == null || scope.isBlank()) ? "NONE" : scope;
    }

    private void validatePerms(List<String> pagePerms, List<String> actionPerms) {
        List<String> validPages = PermCatalog.PAGES.stream().map(p -> p.get("code")).toList();
        List<String> validActions = PermCatalog.ACTIONS.stream().map(a -> a.get("code")).toList();
        if (!validPages.containsAll(pagePerms) || !validActions.containsAll(actionPerms)) {
            throw BizException.badRequest("包含非法权限点");
        }
    }
}
