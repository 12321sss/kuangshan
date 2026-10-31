package com.ganfeng.rs.deformation;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.security.core.Authentication;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;

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
    private final RestTemplate rest;

    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    public DeformationController(DeformationAnalysisService service, PermissionGuard guard,
                                 RestTemplateBuilder builder) {
        this.service = service;
        this.guard = guard;
        this.rest = builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(60))
                .build();
    }

    /**
     * 读取 inference 已产出的形变分析结果（单轨趋势 + 升降轨联合）。
     * 结果 JSON 由 inference 的 analyze 脚本产出，这里只代理读取，不重算。
     */
    @GetMapping("/results")
    public ApiResponse<Map<String, Object>> results(@RequestParam Long projectId,
                                                    Authentication auth) {
        guard.requireAccess(projectId, auth);
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = rest.getForObject(
                    inferenceBaseUrl + "/api/v1/deformation/results", Map.class);
            // inference 返回 {code, message, data:{fusion, tracks}}，取内层 data 直接返回，
            // 避免前端拿到 {data:{code,message,data:{...}}} 这种双重嵌套
            @SuppressWarnings("unchecked")
            Map<String, Object> inner = (resp == null) ? Collections.<String, Object>emptyMap()
                    : (Map<String, Object>) resp.get("data");
            return ApiResponse.ok(inner);
        } catch (Exception e) {
            throw new BizException(500, "读取形变结果失败（请确认 inference 已启动在 "
                    + inferenceBaseUrl + "）：" + e.getMessage());
        }
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
