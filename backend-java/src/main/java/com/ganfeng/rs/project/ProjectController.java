package com.ganfeng.rs.project;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 项目控制器
 * 列表按成员授权过滤；增删改/成员分配需要 action:project-manage
 */
@RestController
@RequestMapping("/api/projects")
public class ProjectController {

    private final ProjectService projectService;
    private final PermissionGuard guard;

    public ProjectController(ProjectService projectService, PermissionGuard guard) {
        this.projectService = projectService;
        this.guard = guard;
    }

    private boolean isAdmin(Authentication auth) {
        return guard.roleCodesOf(auth).contains("ADMIN");
    }

    @GetMapping
    public ApiResponse<List<Project>> list(Authentication auth) {
        return ApiResponse.ok(projectService.listForUser(auth.getName(), isAdmin(auth)));
    }

    @GetMapping("/{id}")
    public ApiResponse<Project> get(@PathVariable long id, Authentication auth) {
        projectService.requireAccess(id, auth.getName(), isAdmin(auth));
        return ApiResponse.ok(projectService.get(id));
    }

    @PostMapping
    public ApiResponse<Project> create(@RequestBody Project req, Authentication auth) {
        guard.require(auth, "action:project-manage");
        return ApiResponse.ok(projectService.create(req));
    }

    @PutMapping("/{id}")
    public ApiResponse<Project> update(@PathVariable long id, @RequestBody Project req, Authentication auth) {
        guard.require(auth, "action:project-manage");
        return ApiResponse.ok(projectService.update(id, req));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:project-manage");
        projectService.delete(id);
        return ApiResponse.ok(null);
    }

    /** 成员分配：body 为用户名数组 */
    @PutMapping("/{id}/members")
    public ApiResponse<Project> setMembers(@PathVariable long id, @RequestBody List<String> members,
                                           Authentication auth) {
        guard.require(auth, "action:project-manage");
        return ApiResponse.ok(projectService.setMembers(id, members));
    }

    /** 合规边界：返回矿权红线/扰动边界/生态红线（GeoJSON 环），供 GIS 大屏叠加 */
    @GetMapping("/{id}/boundary")
    public ApiResponse<String> boundary(@PathVariable long id, Authentication auth) {
        projectService.requireAccess(id, auth.getName(), isAdmin(auth));
        String json = projectService.get(id).getBoundaryJson();
        return ApiResponse.ok(json == null ? "{}" : json);
    }
}
