package com.ganfeng.rs.deformation;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 形变分析结果控制器：按项目隔离（与其它业务控制器同模式）。
 *
 * 端点：
 *   GET    /api/deformation?projectId=     列表（未删除）
 *   GET    /api/deformation/all?projectId= 全部（含回收站）
 *   POST   /api/deformation                新建（Java 侧落库，数据由 inference 产出）
 *   DELETE /api/deformation/{id}           软删除（进回收站）
 *   POST   /api/deformation/{id}/restore   恢复
 *   DELETE /api/deformation/{id}/purge     彻底删除
 */
@RestController
@RequestMapping("/api/deformation")
public class DeformationController {

    private final DeformationAnalysisService service;
    private final PermissionGuard guard;

    public DeformationController(DeformationAnalysisService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<DeformationAnalysis>> list(@RequestParam Long projectId,
                                                       Authentication auth) {
        guard.requireAccess(projectId, auth);
        return ApiResponse.ok(service.list(projectId));
    }

    @GetMapping("/all")
    public ApiResponse<List<DeformationAnalysis>> listAll(@RequestParam Long projectId,
                                                          Authentication auth) {
        guard.requireAccess(projectId, auth);
        return ApiResponse.ok(service.listAll(projectId));
    }

    @PostMapping
    public ApiResponse<DeformationAnalysis> create(@RequestBody DeformationAnalysis entity,
                                                   Authentication auth) {
        guard.requireAccess(entity.getProjectId(), auth);
        entity.setCreatedBy(auth.getName());
        return ApiResponse.ok(service.create(entity));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> softDelete(@PathVariable Long id, Authentication auth) {
        DeformationAnalysis d = service.get(id);
        guard.requireAccess(d.getProjectId(), auth);
        service.softDelete(id, auth.getName());
        return ApiResponse.ok(null);
    }

    @PostMapping("/{id}/restore")
    public ApiResponse<Void> restore(@PathVariable Long id, Authentication auth) {
        DeformationAnalysis d = service.get(id);
        guard.requireAccess(d.getProjectId(), auth);
        service.restore(id);
        return ApiResponse.ok(null);
    }

    @DeleteMapping("/{id}/purge")
    public ApiResponse<Void> purge(@PathVariable Long id, Authentication auth) {
        DeformationAnalysis d = service.get(id);
        guard.requireAccess(d.getProjectId(), auth);
        service.purge(id);
        return ApiResponse.ok(null);
    }
}
